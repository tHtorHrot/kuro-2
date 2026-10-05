"""Validated configuration; secrets may be supplied as files, never as defaults."""

import os
from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class ConfigurationError(RuntimeError):
    """Safe configuration error with no secret value in its message."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_", extra="forbid", hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    token_pepper: SecretStr
    default_timezone: str = "Asia/Jakarta"
    db_pool_size: int = Field(default=3, ge=1, le=20)
    db_max_overflow: int = Field(default=2, ge=0, le=20)
    db_statement_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    max_request_bytes: int = Field(default=65536, ge=1024, le=1048576)
    body_timeout_seconds: float = Field(default=10, ge=1, le=30)
    requests_per_minute: int = Field(default=120, ge=1, le=2000)
    rate_limit_max_clients: int = Field(default=2048, ge=10, le=100000)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    docs_enabled: bool = False

    # User decisions, deliberately constrained rather than freely switchable.
    infrastructure_target_idr: int = Field(default=100000, ge=0)
    premium_mode: Literal["confirm_each_use"] = "confirm_each_use"
    cloud_privacy: Literal["no_training_zdr"] = "no_training_zdr"

    @field_validator("database_url")
    @classmethod
    def valid_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if (
                url.drivername != "postgresql+psycopg"
                or not url.database
                or url.username != "jarvis_app"
            ):
                raise ValueError
            if not url.password or not url.host:
                raise ValueError
        except Exception as exc:
            raise ValueError("Expected a complete PostgreSQL psycopg URL for jarvis_app") from exc
        return value

    @field_validator("token_pepper")
    @classmethod
    def strong_pepper(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 43:
            raise ValueError("Use at least 32 random bytes encoded as URL-safe text")
        return value

    @field_validator("default_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def explicit_hosts(cls, values: list[str]) -> list[str]:
        if not values or any("*" in v or "/" in v or not v.strip() for v in values):
            raise ValueError("Provide explicit host names; wildcards are not allowed")
        return values

    @model_validator(mode="after")
    def production_checks(self) -> Self:
        if self.environment == "production" and (self.docs_enabled or self.log_level == "DEBUG"):
            raise ValueError("Production disallows public API docs and debug logging")
        return self

    def redacted_values(self) -> list[str]:
        raw = self.database_url.get_secret_value()
        return [raw, make_url(raw).password or "", self.token_pepper.get_secret_value()]


def read_secret(name: str, *, required: bool = True) -> str | None:
    """An explicit *_FILE is authoritative. Ambiguous sources fail closed."""
    direct, filename = os.getenv(name), os.getenv(f"{name}_FILE")
    if direct is not None and filename is not None:
        raise ConfigurationError(f"Set only {name} or {name}_FILE")
    if filename is not None:
        try:
            path = Path(filename)
            if not path.is_file() or path.stat().st_size > 16384:
                raise ValueError
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, ValueError, UnicodeError) as exc:
            raise ConfigurationError(f"Cannot read {name}_FILE") from exc
    else:
        value = direct
    if required and not value:
        raise ConfigurationError(f"Missing {name} or {name}_FILE")
    return value


def load_settings() -> Settings:
    from pydantic import ValidationError

    try:
        return Settings(
            database_url=read_secret("JARVIS_DATABASE_URL"),
            token_pepper=read_secret("JARVIS_TOKEN_PEPPER"),
        )
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) if e["loc"] else "settings" for e in exc.errors()})
        raise ConfigurationError("Invalid configuration fields: " + ", ".join(fields)) from None
