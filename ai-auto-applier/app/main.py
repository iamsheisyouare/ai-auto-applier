import os
import uuid
from typing import Optional
import httpx
from fastapi import FastAPI, Depends, Request, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import crud
from app.models import FilterSettings, Vacancy, Application, Area
from app.hh_oauth import (build_hh_authorize_url, exchange_code_for_tokens, search_vacancies,
                          build_vacancy_search_params, save_vacancies_to_db, apply_to_vacancy,
                          update_vacancy_description_in_db)
from app.gigachat_api import generate_cover_letter

app = FastAPI(title="AI Auto Applier MVP")

# ====== DI для БД ======
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ====== Примитивная "авторизация" пользователя (MVP) ======
# Для локальных тестов можно хардкодить user_id или брать из query/header
def current_user_id(request: Request) -> str:
    # В реальном проекте — JWT/сессия. Здесь — заглушка
    return request.headers.get("X-User-Id") or os.getenv("DEV_USER_ID") or str(uuid.uuid4())


@app.get("/test")
async def test():
    print("✅ Это print в консоль")
    return {"message": "Логи работают!"}

# ====== HH OAuth ======
@app.get("/auth/hh/authorize", tags=["Authorization"])
async def hh_authorize(
        request: Request,
        redirect: bool = True,
        skip_choose_account: bool = Query(default=False),
        force_login: bool = Query(default=False),
):
    # в state можно положить CSRF-токен/nonce
    state = str(uuid.uuid4())
    url = build_hh_authorize_url(state, skip_choose_account, force_login)
    if redirect:
        return RedirectResponse(url)
    return {"authorize_url": url, "state": state}

@app.get("/auth/hh/callback", tags=["Authorization"])
async def hh_callback(code: Optional[str] = None, error: Optional[str] = None, request: Request = None, db: Session = Depends(get_db)):
    if error:
        raise HTTPException(status_code=400, detail=f"HH authorization error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    user_id = current_user_id(request)
    token = await exchange_code_for_tokens(db, user_id, code)
    return {"status": "ok", "service": "hh.ru", "expires_at": token.expires_at}


# ====== Поиск вакансий через HH ======
class VacancySearchQuery(BaseModel):
    text: Optional[str] = None
    professional_role: Optional[str] = None  # название роли
    experience: Optional[str] = None
    area: Optional[str] = None               # название региона/города
    work_format: Optional[str] = None        # remote, office, hybrid
    salary: Optional[int] = None
    page: Optional[int] = 0
    per_page: Optional[int] = 20

# Получаем valid_areas из БД
def get_valid_areas(db: Session) -> set[int]:
    return {area.id for area in db.query(Area.id).all()}

@app.get("/vacancies/search", tags=["Vacancies"])
async def vacancies_search_get(
        request: Request,
        text: str = Query(None),
        professional_role: str = Query(None),
        experience: str = Query(None),
        area: str = Query(None),
        work_format: str = Query(None),
        salary: int = Query(None),
        page: int = Query(0),
        per_page: int = Query(20),
        db: Session = Depends(get_db),
):
    user_id = current_user_id(request)

    # Собираем параметры в словарь
    params_dict = {
        "text": text,
        "professional_role": professional_role,
        "experience": experience,
        "area": area,
        "work_format": work_format,
        "salary": salary,
        "page": page,
        "per_page": per_page,
    }

    # Формируем корректные параметры для HH API
    filtered_params = build_vacancy_search_params(params_dict)

    # Получаем все валидные area_id из БД
    valid_areas = get_valid_areas(db)

    try:
        # Запрос к HH
        resp = await search_vacancies(db, user_id, filtered_params)
        # Сохраняем вакансии в БД
        save_vacancies_to_db(db, user_id, resp, valid_areas)
        return resp
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

@app.get("/vacancies/{vacancy_id}/update_description", tags=["Vacancies"])
async def update_vacancy_description(vacancy_id: str, request: Request, db: Session = Depends(get_db)):
    user_id = current_user_id(request)
    updated = await update_vacancy_description_in_db(db, user_id, vacancy_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Vacancy not found in DB")
    return {"vacancy_id": vacancy_id, "updated_description": True}

# ====== Генерация сопроводительного письма ======
class CoverLetterIn(BaseModel):
    vacancy_description: str
    resume_text: str
    tone: Optional[str] = "formal"
    max_length: Optional[int] = None

class CoverLetterOut(BaseModel):
    cover_letter: str

@app.post("/cover-letter/generate", response_model=CoverLetterOut, tags=["CoverLetter"])
async def cover_letter_generate(body: CoverLetterIn, request: Request, db: Session = Depends(get_db)):
    user_id = current_user_id(request)
    text = await generate_cover_letter(
        db=db,
        user_id=user_id,
        vacancy_text=body.vacancy_description,
        resume_text=body.resume_text,
        tone=body.tone or "formal",
        max_length=body.max_length,
    )
    return CoverLetterOut(cover_letter=text)

# ====== Создать отклик: генерация письма (если нужно) + отправка в HH ======
class ApplicationCreateIn(BaseModel):
    hh_vacancy_id: str
    resume_id: Optional[str] = None  # твой внутренний ID (пока не используем)
    cover_letter: Optional[str] = None
    tone: Optional[str] = "formal"
    send_now: bool = True

@app.post("/applications", tags=["Applications"])
async def create_application_endpoint(body: ApplicationCreateIn, request: Request, db: Session = Depends(get_db)):
    user_id = current_user_id(request)

    # 1) Получить описание вакансии для генерации письма (минимум текст из HH)
    # Для MVP упростим: используем только hh_vacancy_id → добавь при желании отдельный /vacancy/{id}
    vacancy_desc = f"Вакансия {body.hh_vacancy_id}. (Для улучшения генерации подтяни описание вакансии из HH /vacancies/{{id}})"

    # 2) Если cover_letter не передали — генерируем в GigaChat
    cover_letter = body.cover_letter
    if not cover_letter:
        cover_letter = await generate_cover_letter(
            db=db,
            user_id=user_id,
            vacancy_text=vacancy_desc,
            resume_text="(Вставь здесь текст резюме пользователя из БД/формы — MVP заглушка)",
            tone=body.tone or "formal",
        )

    # 3) Сохраняем Application (pending)
    app_obj = Application(
        vacancy_id=None,  # можно заранее сохранить Vacancy и связать, если хочешь
        user_id=user_id,
        status="pending",
        cover_letter=cover_letter,
    )
    app_obj = crud.create_application(db, app_obj)

    # 4) Отправка в HH (если send_now=True)
    hh_resp = None
    if body.send_now:
        try:
            # В HH нужно резюме id. Для MVP оставим фиктивным или возьми из настроек
            fake_resume_id = os.getenv("HH_TEST_RESUME_ID", "your-hh-resume-id")
            hh_resp = await apply_to_vacancy(db, user_id, body.hh_vacancy_id, fake_resume_id, cover_letter)
            crud.update_application_status(db, app_obj.id, status="sent")
            crud.add_log(db, user_id, "application_sent", f"hh_response={hh_resp}")
        except httpx.HTTPStatusError as e:
            crud.update_application_status(db, app_obj.id, status="error")
            crud.add_log(db, user_id, "application_error", e.response.text)
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    return {
        "application_id": str(app_obj.id),
        "status": app_obj.status,
        "hh_response": hh_resp,
        "cover_letter": cover_letter,
    }