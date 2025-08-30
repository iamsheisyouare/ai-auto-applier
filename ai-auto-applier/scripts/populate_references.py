import asyncio
import datetime
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Skill, ProfessionalRole, Industry, Area
from app.hh_oauth import get_skills, get_professional_roles, get_industries

# ⚠ user_id = тот пользователь, который авторизован в HH
USER_ID = "uuid-пользователя"

async def populate_professional_roles(db: Session, user_id: str):
    data = await get_professional_roles(db, user_id)
    for category in data.get("categories", []):
        for role in category.get("roles", []):
            role_id = role["id"]
            name = role["name"]
            obj = db.query(ProfessionalRole).filter(ProfessionalRole.id == role_id).first()
            if not obj:
                obj = ProfessionalRole(id=role_id, name=name, category=category["name"])
                db.add(obj)
            else:
                obj.name = name
                obj.category = category["name"]
    db.commit()
    print("✅ Professional roles updated")

async def populate_industries(db: Session, user_id: str):
    data = await get_industries(db, user_id)
    for item in data:
        obj = db.query(Industry).filter(Industry.id == item["id"]).first()
        if not obj:
            obj = Industry(id=item["id"], name=item["name"], category=None)
            db.add(obj)
        else:
            obj.name = item["name"]
        obj.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()
    print("✅ Industries updated")

async def populate_skills(db: Session, user_id: str, skill_ids: list[int]):
    data = await get_skills(db, user_id, skill_ids)
    for item in data.get("items", []):
        obj = db.query(Skill).filter(Skill.id == int(item["id"])).first()
        if not obj:
            obj = Skill(id=int(item["id"]), name=item["text"], category=None)
            db.add(obj)
        else:
            obj.name = item["text"]
        obj.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()
    print("✅ Skills updated")

async def main():
    db: Session = SessionLocal()
    try:
        await populate_professional_roles(db, USER_ID)
        await populate_industries(db, USER_ID)
        await populate_skills(db, USER_ID, [2716, 3019, 0])  # пример: SQL, Python, Java
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())