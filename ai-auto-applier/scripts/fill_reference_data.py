import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import NoResultFound
from dotenv import load_dotenv
import httpx


from app.models import Area, ProfessionalRole, Industry, ApiToken, Base
from app.database import SessionLocal, DATABASE_URL

load_dotenv()
HH_USER_AGENT_EMAIL = os.getenv("HH_USER_AGENT_EMAIL")

# --- Настройка БД ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


# =================== ФУНКЦИИ ===================

def get_hh_token(db: SessionLocal, user_id):
    """
    Берем access_token для hh.ru из БД
    """
    token = db.query(ApiToken).filter(ApiToken.user_id == user_id, ApiToken.service_name=="hh.ru").first()
    if not token:
        raise RuntimeError("Токен hh.ru не найден для пользователя", user_id)
    return token.access_token

async def fetch_json(url: str, token: str, params=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "HH-User-Agent": "AI-Auto-Applier/1.0 ({HH_USER_AGENT_EMAIL})"
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

def upsert_area(db, area_data):
    """
    Сохраняем область в БД
    """
    obj = db.query(Area).filter(Area.id==area_data["id"]).first()
    if not obj:
        obj = Area(id=area_data["id"], name=area_data["name"], parent_id=area_data.get("parent_id"))
        db.add(obj)
    else:
        obj.name = area_data["name"]
        obj.parent_id = area_data.get("parent_id")
    db.commit()

def upsert_professional_role(db, role_data):
    """
    role_data: {
        'id': str,
        'name': str,
        'category': str
    }
    """
    obj = db.query(ProfessionalRole).filter(ProfessionalRole.id == role_data["id"]).first()
    if not obj:
        obj = ProfessionalRole(
            id=role_data["id"],
            name=role_data["name"],
            category=role_data.get("category")  # <-- теперь здесь точно есть строка
        )
        db.add(obj)
    else:
        obj.name = role_data["name"]
        obj.category = role_data.get("category")
    db.commit()

def upsert_industry(db, industry_data):
    """
    industry_data: {
        'id': str,
        'name': str,
        'category': Optional[str]
    }
    """
    obj = db.query(Industry).filter(Industry.id == industry_data["id"]).first()
    if not obj:
        obj = Industry(
            id=industry_data["id"],
            name=industry_data["name"],
            category=industry_data.get("category")
        )
        db.add(obj)
    else:
        obj.name = industry_data["name"]
        obj.category = industry_data.get("category")
    obj.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()

# =================== MAIN ===================
import asyncio

async def main():
    db = SessionLocal()
    user_id = "98e293a4-513a-4e78-b0f2-6a22320f3a34"

    token = get_hh_token(db, user_id)

    # ===== Areas =====
    areas = await fetch_json("https://api.hh.ru/areas", token)
    for area in areas:
        upsert_area(db, {"id": area["id"], "name": area["name"], "parent_id": None})
        if "areas" in area:
            for sub in area["areas"]:
                upsert_area(db, {"id": sub["id"], "name": sub["name"], "parent_id": area["id"]})

    print("Areas заполнены")

    # ===== Professional Roles =====
    response = await fetch_json("https://api.hh.ru/professional_roles", token)

    for category in response.get("categories", []):
        category_id = category.get("id")
        category_name = category.get("name")

        for role in category.get("roles", []):
            # Добавляем поле category для связи с категорией
            role_data = {
                "id": role["id"],
                "name": role["name"],
                "category": category_name
            }
            upsert_professional_role(db, role_data)

    print("Professional Roles заполнены")

    # ===== Industries =====
    industries = await fetch_json("https://api.hh.ru/industries", token)
    for category in industries:
        # сначала родитель
        upsert_industry(db, {
            "id": category["id"],
            "name": category["name"],
            "category": None
        })

        # затем вложенные
        for sub in category.get("industries", []):
            upsert_industry(db, {
                "id": sub["id"],
                "name": sub["name"],
                "category": category["id"]
            })

    print("Industries заполнены")

    db.close()

if __name__ == "__main__":
    asyncio.run(main())