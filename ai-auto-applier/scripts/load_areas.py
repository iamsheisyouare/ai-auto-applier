import asyncio
import httpx
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Area

async def load_areas():
    url = "https://api.hh.ru/areas"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

    db: Session = SessionLocal()
    try:
        def insert_node(node):
            area = Area(id=int(node["id"]), name=node["name"])
            db.merge(area)
            for sub in node.get("areas", []):
                insert_node(sub)

        for root in data:
            insert_node(root)
        db.commit()
        print("Areas loaded successfully")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(load_areas())