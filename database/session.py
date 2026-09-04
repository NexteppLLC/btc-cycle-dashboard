"""Engine/session factory isolated for future PostgreSQL migration."""
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from .models import Base


def get_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def create_schema(database_url: str | None = None) -> None:
    Base.metadata.create_all(get_engine(database_url))


@contextmanager
def session_scope(database_url: str | None = None):
    session = sessionmaker(get_engine(database_url), expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

