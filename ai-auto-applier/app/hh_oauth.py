import os
import datetime
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from app.models import User
from sqlalchemy.exc import NoResultFound
from app.crud import upsert_api_token, get_api_token
from app.models import Vacancy

load_dotenv()

# Загружаем переменные окружения (CLIENT_ID, CLIENT_SECRET и т.д.)
HH_CLIENT_ID = os.getenv("HH_CLIENT_ID")
HH_CLIENT_SECRET = os.getenv("HH_CLIENT_SECRET")
HH_REDIRECT_URI = os.getenv("HH_REDIRECT_URI", "http://localhost:8000/auth/hh/callback")
HH_USER_AGENT_EMAIL = os.getenv("HH_USER_AGENT_EMAIL")
DEV_USER_ID = os.getenv("DEV_USER_ID")

# URLs для API hh.ru
AUTH_URL = "https://hh.ru/oauth/authorize" # для авторизации пользователя
TOKEN_URL = "https://api.hh.ru/token" # для получения/обновления токенов
VACANCIES_URL = "https://api.hh.ru/vacancies" # для поиска вакансий
APPLY_URL_TMPL = "https://api.hh.ru/negotiations"  # конечная точка для отклика (см. доки hh)

# ===================== OAUTH =====================
# Строим ссылку для авторизации пользователя через HH

def build_hh_authorize_url(state: str, skip_choose_account: bool = False, force_login: bool = False) -> str:
    """
    Формируем URL для перехода пользователя на HH для авторизации.
    state — уникальная строка для защиты от CSRF.
    skip_choose_account — если True, сразу логинит в последний аккаунт.
    force_login — если True, потребует повторный вход.
    """
    params = {
        "response_type": "code",      # используем authorization code flow
        "client_id": HH_CLIENT_ID,    # ID приложения
        "redirect_uri": HH_REDIRECT_URI,  # куда вернется пользователь после авторизации
        "state": state,
    }
    if skip_choose_account:
        params["skip_choose_account"] = "true"
    if force_login:
        params["force_login"] = "true"
    return f"{AUTH_URL}?{urlencode(params)}"

# Обмен кода авторизации на токены
async def exchange_code_for_tokens(db: Session, user_id, code: str):
    """
    Получаем access_token и refresh_token по коду авторизации.
    Сохраняем их в БД через upsert_api_token.
    """
    try:
        user = db.query(User).filter(User.id == user_id).one()
    except NoResultFound:
        # Если пользователя нет, создаём
        user = User(id=user_id, name="Unknown", email=f"user_{user_id}@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": HH_REDIRECT_URI,
        "client_id": HH_CLIENT_ID,
        "client_secret": HH_CLIENT_SECRET,
    }

    # Отправляем POST-запрос к hh.ru для получения токенов
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        r.raise_for_status()
        j = r.json()

    # Получаем токены и время жизни
    access_token = j.get("access_token")
    refresh_token = j.get("refresh_token")
    expires_in = j.get("expires_in")  # в секундах
    expires_at = None
    if expires_in:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=int(expires_in))

    # Сохраняем в БД
    return upsert_api_token(db, user_id, "hh.ru", access_token, refresh_token, expires_at)

# Обновление access_token по refresh_token
async def refresh_hh_access_token(db: Session, user_id):
    """
    Если access_token истек, используем refresh_token для получения нового.
    """
    token = get_api_token(db, user_id, "hh.ru")
    if not token or not token.refresh_token:
        raise RuntimeError("Нет refresh_token для hh.ru")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
        "client_id": HH_CLIENT_ID,
        "client_secret": HH_CLIENT_SECRET,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        r.raise_for_status()
        j = r.json()

    access_token = j.get("access_token")
    refresh_token = j.get("refresh_token")
    expires_in = j.get("expires_in")
    expires_at = None
    if expires_in:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=int(expires_in))

    return upsert_api_token(db, user_id, "hh.ru", access_token, refresh_token, expires_at)

# Получение заголовков для авторизованных запросов
async def hh_authorized_headers(db: Session, user_id=None) -> dict:
    """
    Возвращает словарь headers с действующим access_token.
    Если токен устарел — обновляет.
    """
    if user_id is None:
        if DEV_USER_ID is None:
            raise RuntimeError("DEV_USER_ID не задан в .env")
        user_id = DEV_USER_ID  # используем тестовый user_id

    token = get_api_token(db, user_id, "hh.ru")
    if not token:
        raise RuntimeError("Токен hh.ru не найден, авторизуйтесь")

    if token.expires_at and token.expires_at <= datetime.datetime.now(datetime.timezone.utc):
        token = await refresh_hh_access_token(db, user_id)

    return {
        "Authorization": f"Bearer {token.access_token}",
        "HH-User-Agent": f"AI-Auto-Applier/1.0 ({HH_USER_AGENT_EMAIL})"
    }

# ===================== ВАКАНСИИ =====================
# Поиск вакансий
async def search_vacancies(db: Session, user_id, params: dict) -> dict:
    """
    Проксируем поиск в HH /vacancies
    params может содержать: text, area, salary, page, per_page, и т.д.
    """
    headers = await hh_authorized_headers(db, user_id)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(VACANCIES_URL, headers=headers, params=params)
        r.raise_for_status()
        return r.json()

# Построение параметров поиска через словарь фильтров
def build_vacancy_search_params(filters: dict) -> dict:
    params = {
        "per_page": filters.get("per_page", 20),
        "page": filters.get("page", 0),
        "no_magic": "true",
    }
    for key in ["professional_role", "experience", "area", "work_format", "text", "salary"]:
        if filters.get(key):
            params[key] = filters[key]
    if filters.get("salary"):
        params["only_with_salary"] = "true"
    return params

# Проверка, что area_id существует в справочнике
def is_valid_area(area_id: int, valid_areas: set) -> bool:
    return area_id in valid_areas

# Сохранение вакансий в БД
def save_vacancies_to_db(db: Session, user_id, vacancies_data, valid_areas: set):
    for vac in vacancies_data.get("items", []):
        area_id = int(vac["area"]["id"])

        # проверка валидности area_id
        if not is_valid_area(area_id, valid_areas):
            print(f"⚠️ Пропущена вакансия {vac['id']} — неизвестный area_id: {area_id}")
            continue

        vacancy = Vacancy(
            hh_vacancy_id=vac["id"],
            user_id=user_id,
            area_id=area_id,
            title=vac["name"],
            experience=vac.get("experience", {}).get("id"),
            company=vac["employer"]["name"] if vac.get("employer") else None,
            description=vac.get("snippet", {}).get("requirement"),
            url=vac["alternate_url"],
            published_at=vac["published_at"]
        )
        db.add(vacancy)

    db.commit()

# Отправка отклика на вакансию
async def apply_to_vacancy(db: Session, user_id, vacancy_id: str, resume_id: str, message: str) -> dict:
    """
    POST к /negotiations для отклика на вакансию.
    vacancy_id — ID вакансии в HH
    resume_id — ID резюме в HH
    message — сопроводительное письмо
    """
    headers = await hh_authorized_headers(db, user_id)
    body = {
        "vacancy_id": vacancy_id,
        "resume_id": resume_id,
        "message": message,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(APPLY_URL_TMPL, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

# ===================== СПРАВОЧНИКИ =====================
# Только через OAuth, с HH-User-Agent

# Получение профессиональных ролей
async def get_professional_roles(db: Session, user_id, locale: str = "RU") -> dict:
    """
    Возвращает роли, категории и ID для фильтров вакансий.
    """
    headers = await hh_authorized_headers(db, user_id)
    url = "https://api.hh.ru/professional_roles"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers, params={"locale": locale})
        r.raise_for_status()
        return r.json()


# Получение отраслей
async def get_industries(db: Session, user_id, locale: str = "RU") -> dict:
    """
    Справочник отраслей для фильтрации вакансий
    """
    headers = await hh_authorized_headers(db, user_id)
    url = "https://api.hh.ru/industries"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers, params={"locale": locale})
        r.raise_for_status()
        return r.json()