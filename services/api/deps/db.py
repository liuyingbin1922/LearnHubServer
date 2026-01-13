from typing import Generator

from sqlalchemy.orm import Session

from shared.db import get_session_factory


SessionLocal = get_session_factory()


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
