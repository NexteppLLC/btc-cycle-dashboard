"""Environment-backed settings; secrets are never embedded in source."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment or an untracked .env."""

    database_url: str = f"sqlite:///{ROOT / 'data' / 'btc_cycle.db'}"
    glassnode_api_key: str | None = None
    etf_flow_csv_url: str | None = None
    http_timeout_seconds: float = 20.0
    cache_ttl_seconds: int = 900
    gold_price_priority: str = "XAUUSD=X,GC=F,GLD"
    silver_price_priority: str = "XAGUSD=X,SI=F,SLV"
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
