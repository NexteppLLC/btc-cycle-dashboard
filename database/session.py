"""Engine/session factory isolated for future PostgreSQL migration."""
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from .models import Base


def get_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def create_schema(database_url: str | None = None) -> None:
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    # create_all does not add columns to an existing SQLite database.  Keep the
    # deployed, user-owned history and apply this small backwards-compatible migration.
    additions = {
        "metrics": {"asset": "VARCHAR(12)", "price_type": "VARCHAR(30)", "effective_date": "DATE", "error": "VARCHAR(500)"},
        "etf_holdings": {"effective_date": "DATE", "published_at": "DATETIME", "error": "VARCHAR(500)",
                         "physical_holdings": "FLOAT", "holdings_unit": "VARCHAR(20)", "net_assets": "FLOAT"},
    }
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            for table, columns in additions.items():
                existing = {c["name"] for c in inspect(connection).get_columns(table)}
                for name, sql_type in columns.items():
                    if name not in existing:
                        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {sql_type}'))


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
