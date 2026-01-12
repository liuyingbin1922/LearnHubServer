from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from shared.config import get_settings


class Base(DeclarativeBase):
    pass


def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session_factory():
    engine = get_engine()
    return sessionmaker(bind=engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.utcnow()
