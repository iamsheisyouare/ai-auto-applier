import os
import uuid
import datetime
import httpx
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.crud import get_api_token, upsert_api_token

load_dotenv()

GIGA_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGA_API_BASE = "https://gigachat.devices.sberbank.ru"
GIGA_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")

# Basic <Authorization key> — см. личный кабинет GigaChat
GIGA_AUTH_BASIC = os.getenv("GIGACHAT_AUTH_BASIC")

def _now():
    return datetime.datetime.now(datetime.UTC)

async def _get_fresh_giga_token(db: Session, user_id):
    """
    Получить новый access token GigaChat по Basic-схеме.
    """
    if not GIGA_AUTH_BASIC:
        raise RuntimeError("GIGACHAT_AUTH_BASIC не задан")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {GIGA_AUTH_BASIC}",
    }
    data = {"scope": GIGA_SCOPE}
    async with httpx.AsyncClient(timeout=30, verify=True) as client:
        r = await client.post(GIGA_AUTH_URL, headers=headers, data=data)
        r.raise_for_status()
        j = r.json()

    access_token = j.get("access_token")
    expires_at = None
    # У GigaChat токен ~30 минут. Если вернулся expires_at/expires_in — учитываем.
    if "expires_at" in j:
        try:
            expires_at = datetime.datetime.fromisoformat(j["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=datetime.UTC)
        except Exception:
            expires_at = _now() + datetime.timedelta(minutes=29)
    elif "expires_in" in j:
        expires_at = _now() + datetime.timedelta(seconds=int(j["expires_in"]))
    else:
        expires_at = _now() + datetime.timedelta(minutes=29)

    # сохраняем как сервис "gigaChat"
    return upsert_api_token(db, user_id, "gigaChat", access_token, None, expires_at)

async def giga_bearer(db: Session, user_id) -> str:
    """
    Валидный Bearer для GigaChat (автообновление).
    """
    tok = get_api_token(db, user_id, "gigaChat")
    if not tok or not tok.access_token or (tok.expires_at and tok.expires_at <= _now()):
        tok = await _get_fresh_giga_token(db, user_id)
    return tok.access_token

async def generate_cover_letter(db: Session, user_id, vacancy_text: str, resume_text: str, tone: str = "formal", max_length: int | None = None) -> str:
    """
    Генерация сопроводительного письма через GigaChat.
    Здесь используем chat-completions-подобный эндпоинт (проверь точный у себя в кабинете).
    """
    bearer = await giga_bearer(db, user_id)

    system_prompt = (
        "Ты — помощник-составитель сопроводительных писем. "
        "На основе описания вакансии и резюме кандидата сформируй краткое, конкретное письмо. "
        f"Тональность: {'официальная' if tone == 'formal' else 'дружелюбная'}."
    )
    user_prompt = f"Вакансия:\n{vacancy_text}\n\nРезюме:\n{resume_text}\n\nСформируй сопроводительное письмо."

    payload = {
        "model": os.getenv("GIGACHAT_MODEL", "GigaChat"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.5,
    }
    if max_length:
        payload["max_tokens"] = max_length

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
    }

    url = f"{GIGA_API_BASE}/api/v1/chat/completions"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        j = r.json()

    # адаптируй под фактический формат ответа GigaChat
    try:
        return j["choices"][0]["message"]["content"]
    except Exception:
        # про запас
        return str(j)
