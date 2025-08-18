import os
import uuid
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

HH_CLIENT_ID = os.getenv("HH_CLIENT_ID")
HH_CLIENT_SECRET = os.getenv("HH_CLIENT_SECRET")
HH_REDIRECT_URI = os.getenv("HH_REDIRECT_URI", "http://localhost:8000/auth/hh/callback")

AUTH_URL = "https://hh.ru/oauth/authorize"
TOKEN_URL = "https://api.hh.ru/token"
VACANCIES_URL = "https://api.hh.ru/vacancies"
APPLY_URL_TMPL = "https://api.hh.ru/negotiations"  # конечная точка для отклика (см. доки hh)

def build_hh_authorize_url(state: str, skip_choose_account: bool = False, force_login: bool = False) -> str:
    """
    Формируем URL авторизации HH (authorization code flow)
    """
    assert HH_CLIENT_ID, "HH_CLIENT_ID не задан"
    params = {
        "response_type": "code",
        "client_id": HH_CLIENT_ID,
        "redirect_uri": HH_REDIRECT_URI,
        "state": state,
    }
    if skip_choose_account:
        params["skip_choose_account"] = "true"
    if force_login:
        params["force_login"] = "true"
    return f"{AUTH_URL}?{urlencode(params)}"

async def exchange_code_for_tokens(db: Session, user_id, code: str):
    """
    Обмениваем authorization_code на access/refresh токены, сохраняем в ApiTokens.
    """
    try:
        user = db.query(User).filter(User.id == user_id).one()
    except NoResultFound:
        # Если пользователя нет, создаём (или можно выбросить ошибку)
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
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        r.raise_for_status()
        j = r.json()
    access_token = j.get("access_token")
    refresh_token = j.get("refresh_token")
    expires_in = j.get("expires_in")  # секунд
    expires_at = None
    if expires_in:
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=int(expires_in))
    return upsert_api_token(db, user_id, "hh.ru", access_token, refresh_token, expires_at)

async def refresh_hh_access_token(db: Session, user_id):
    """
    Обновляем access_token по refresh_token.
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
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=int(expires_in))
    return upsert_api_token(db, user_id, "hh.ru", access_token, refresh_token, expires_at)

async def hh_authorized_headers(db: Session, user_id) -> dict:
    """
    Возвращает заголовки с валидным access_token, при необходимости обновляет его.
    """
    token = get_api_token(db, user_id, "hh.ru")
    if not token:
        raise RuntimeError("Токен hh.ru не найден, авторизуйтесь")

    if token.expires_at and token.expires_at <= datetime.datetime.now(datetime.UTC):
        token = await refresh_hh_access_token(db, user_id)

    return {"Authorization": f"Bearer {token.access_token}"}

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



async def apply_to_vacancy(db: Session, user_id, vacancy_id: str, resume_id: str, message: str) -> dict:
    """
    Отправка отклика. В HH используются /negotiations c телом, включающим vacancy_id, resume_id и сообщение.
    Конкретное тело см. в доке HH (может отличаться в зависимости от типа отклика).
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
