import datetime
import uuid
from sqlalchemy import Column, String, Integer, Text, ForeignKey, TIMESTAMP, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

# Пользователь
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255))
    created_at = Column(TIMESTAMP, default=lambda: datetime.datetime.now(datetime.UTC))
    updated_at = Column(TIMESTAMP, onupdate=lambda: datetime.datetime.now(datetime.UTC))

    filter_settings = relationship("FilterSettings", back_populates="user")
    vacancies = relationship("Vacancy", back_populates="user")
    applications = relationship("Application", back_populates="user")
    logs = relationship("Log", back_populates="user")
    api_tokens = relationship("ApiToken", back_populates="user")


# Настройки фильтров
class FilterSettings(Base):
    __tablename__ = "filter_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    city = Column(String(50))
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    work_format = Column(String(50))
    keywords = Column(Text)  # Можно хранить JSON
    created_at = Column(TIMESTAMP, default=lambda: datetime.datetime.now(datetime.UTC))
    updated_at = Column(TIMESTAMP, onupdate=lambda: datetime.datetime.now(datetime.UTC))

    user = relationship("User", back_populates="filter_settings")


# Вакансия
class Vacancy(Base):
    __tablename__ = "vacancies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hh_vacancy_id = Column(String(50))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    title = Column(String(255))
    company = Column(String(255))
    description = Column(Text)
    url = Column(String(500))
    published_at = Column(TIMESTAMP)
    fetched_at = Column(TIMESTAMP, default=lambda: datetime.datetime.now(datetime.UTC))

    user = relationship("User", back_populates="vacancies")
    applications = relationship("Application", back_populates="vacancy")


# Отклик
class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vacancy_id = Column(UUID(as_uuid=True), ForeignKey("vacancies.id"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    applied_at = Column(TIMESTAMP, default=lambda: datetime.datetime.now(datetime.UTC))
    status = Column(String(50))
    cover_letter = Column(Text)

    vacancy = relationship("Vacancy", back_populates="applications")
    user = relationship("User", back_populates="applications")


# Логи
class Log(Base):
    __tablename__ = "logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    action = Column(String(255))
    description = Column(Text)
    created_at = Column(TIMESTAMP, default=lambda: datetime.datetime.now(datetime.UTC))

    user = relationship("User", back_populates="logs")


# API токены
class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    service_name = Column(String(50))
    access_token = Column(Text)
    refresh_token = Column(Text)
    expires_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, default=lambda: datetime.datetime.now(datetime.UTC))
    updated_at = Column(TIMESTAMP, onupdate=lambda: datetime.datetime.now(datetime.UTC))

    user = relationship("User", back_populates="api_tokens")
