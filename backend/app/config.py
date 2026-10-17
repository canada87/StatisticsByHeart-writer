"""Runtime configuration (environment variables prefixed ``SBH_``)."""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SBH_", env_file=None, extra="ignore")

    # Database: either a full URL (tests, tooling) or the discrete parts (compose).
    database_url: str | None = None
    db_host: str = "sbh-db"
    db_port: int = 5432
    db_name: str = "sbh"
    db_user: str = "sbh"
    db_password: SecretStr = SecretStr("")

    # Time handling: day boundaries for daily_metric, and fallback when a record has no offset.
    local_timezone: str = "Europe/Rome"

    # Comma-separated Android package names, most trusted first. Sources not listed rank
    # after the listed ones, ordered by how much data they hold for the day.
    source_priority: str = ""

    # Heart Points: HRmax = hr_max if set, else 205.8 - 0.685 x age (age = day.year - birth_year).
    # Personal values: set them ONLY in the private .env, never in the repository.
    birth_year: int | None = None
    hr_max: int | None = None

    @field_validator("birth_year", "hr_max", mode="before")
    @classmethod
    def _empty_is_unset(cls, v: object) -> object:
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    # Home Assistant alarm: no successful sync for more than this many hours -> "stale".
    stale_hours: float = 6.0
    ha_rate_limit_per_minute: int = 30

    # Ingest limits.
    max_batch_records: int = 500
    max_body_bytes: int = 32 * 1024 * 1024  # after gzip decompression

    # Web session.
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = True
    cookie_name: str = "sbh_session"
    login_max_failures: int = 5
    login_window_seconds: int = 15 * 60

    # Behaviour toggles.
    enable_scheduler: bool = True
    enable_docs: bool = True
    static_dir: str = "/app/static"  # built dashboard; absent = API only

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        ).render_as_string(hide_password=False)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.local_timezone)

    @property
    def source_priority_list(self) -> list[str]:
        return [p.strip() for p in self.source_priority.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
