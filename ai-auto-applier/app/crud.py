import datetime
from typing import Optional, Sequence

from sqlalchemy import select, and_, update
from sqlalchemy.orm import Session

from app.models import User, FilterSettings, Vacancy, Application, Log, ApiToken

# ==== USERS ====
def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.email == email))

def create_user(db: Session, name: str, email: str, password_hash: Optional[str] = None) -> User:
    user = User(name=name, email=email, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

# ==== FILTERS ====
def get_filters_by_user(db: Session, user_id) -> Sequence[FilterSettings]:
    return db.scalars(select(FilterSettings).where(FilterSettings.user_id == user_id)).all()

def save_filter(db: Session, f: FilterSettings) -> FilterSettings:
    db.add(f)
    db.commit()
    db.refresh(f)
    return f

# ==== VACANCIES ====
def save_vacancy(db: Session, v: Vacancy) -> Vacancy:
    db.add(v)
    db.commit()
    db.refresh(v)
    return v

def list_vacancies(db: Session, user_id=None, limit: int = 50) -> Sequence[Vacancy]:
    stmt = select(Vacancy).order_by(Vacancy.fetched_at.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(Vacancy.user_id == user_id)
    return db.scalars(stmt).all()

# ==== APPLICATIONS ====
def create_application(db: Session, application: Application) -> Application:
    db.add(application)
    db.commit()
    db.refresh(application)
    return application

def update_application_status(db: Session, app_id, status: str, cover_letter: Optional[str] = None) -> Optional[Application]:
    stmt = select(Application).where(Application.id == app_id)
    app = db.scalar(stmt)
    if not app:
        return None
    app.status = status
    if cover_letter is not None:
        app.cover_letter = cover_letter
    db.commit()
    db.refresh(app)
    return app

def list_applications(db: Session, user_id=None, vacancy_id=None, status=None) -> Sequence[Application]:
    conditions = []
    if user_id:
        conditions.append(Application.user_id == user_id)
    if vacancy_id:
        conditions.append(Application.vacancy_id == vacancy_id)
    if status:
        conditions.append(Application.status == status)

    stmt = select(Application)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(Application.applied_at.desc())
    return db.scalars(stmt).all()

# ==== LOGS ====
def add_log(db: Session, user_id, action: str, description: str = "") -> Log:
    log = Log(
        user_id=user_id,
        action=action,
        description=description,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log

# ==== TOKENS ====
def get_api_token(db: Session, user_id, service_name: str) -> Optional[ApiToken]:
    return db.scalar(
        select(ApiToken).where(
            and_(
                ApiToken.user_id == user_id,
                ApiToken.service_name == service_name,
                )
        )
    )

def upsert_api_token(
        db: Session,
        user_id,
        service_name: str,
        access_token: str,
        refresh_token: Optional[str],
        expires_at: Optional[datetime.datetime],
) -> ApiToken:
    token = get_api_token(db, user_id, service_name)
    if token:
        token.access_token = access_token
        token.refresh_token = refresh_token
        token.expires_at = expires_at
        token.updated_at = datetime.datetime.now(datetime.UTC)
    else:
        token = ApiToken(
            user_id=user_id,
            service_name=service_name,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(token)
    db.commit()
    db.refresh(token)
    return token
