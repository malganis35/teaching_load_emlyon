"""Application settings loaded from environment variables / .env file."""

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from teaching_load.core.utils.paths import DATA_DIR, PROJECT_ROOT, RAW_DATA_DIR


class Settings(BaseSettings):
    """Runtime configuration (secrets come from the untracked .env file)."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    makersboard_ical_url: str = ""
    ade_ical_url: str = ""
    db_path: Path = DATA_DIR / "teaching.duckdb"
    raw_dir: Path = RAW_DATA_DIR
    default_target_hours: float = 220.0
    default_year_start: date = date(2026, 9, 1)
    default_year_end: date = date(2027, 8, 31)
    http_timeout_s: float = 30.0
    retry_delay_s: float = 5.0


def get_settings() -> Settings:
    """Build a fresh Settings object (cheap, avoids stale env in tests)."""
    return Settings()
