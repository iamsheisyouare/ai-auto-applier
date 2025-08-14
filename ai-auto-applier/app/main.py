import os
import uuid
from typing import Optional, List

import httpx
from fastapi import FastAPI, Depends, Request, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
import app.crud
from app.models import FilterSettings, Vacancy, Application
from app.hh_oauth import build_hh_authorize_url, exchange_code_for_tokens, search_vacancies, apply_to_vacancy
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
    area: Optional[str] = None
    salary: Optional[int] = None
    page: Optional[int] = 0
    per_page: Optional[int] = 20

@app.post("/vacancies/search", tags=["Vacancies"])
async def vacancies_search(q: VacancySearchQuery, request: Request, db: Session = Depends(get_db)):
    user_id = current_user_id(request)
    params = {k: v for k, v in q.model_dump().items() if v is not None}
    try:
        resp = await search_vacancies(db, user_id, params)
        return resp
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

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
