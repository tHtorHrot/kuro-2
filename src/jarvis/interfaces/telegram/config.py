import json
import os
import re
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from jarvis.core.config import ConfigurationError, read_secret


class TelegramConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    owner_id: UUID
    sender_id: int = Field(strict=True, gt=0, lt=2**52)
    bot_id: int = Field(strict=True, gt=0, lt=2**52)
    poll_seconds: int = Field(default=20, strict=True, ge=1, le=30)
    updates_per_poll: int = Field(default=20, strict=True, ge=1, le=100)
    # Kebijakan eksplisit operator: True melarang forward/salin/screenshot
    # balasan bot (privasi), False mengizinkan demi kenyamanan dengan risiko
    # bocor bila perangkat dilihat orang lain. Default tetap terlindungi.
    protect_content: bool = True


def load_telegram_config() -> TelegramConfig:
    filename = os.getenv("JARVIS_TELEGRAM_CONFIG_FILE")
    try:
        if not filename:
            raise ValueError
        path = Path(filename)
        if not path.is_file() or path.stat().st_size > 4096:
            raise ValueError
        return TelegramConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError):
        raise ConfigurationError("Invalid or missing JARVIS_TELEGRAM_CONFIG_FILE") from None


def load_bot_token(config: TelegramConfig) -> SecretStr:
    raw = read_secret("JARVIS_TELEGRAM_BOT_TOKEN")
    if not raw or not re.fullmatch(r"[1-9][0-9]{0,15}:[A-Za-z0-9_-]{30,100}", raw):
        raise ConfigurationError("Invalid Telegram bot token format")
    if int(raw.split(":", 1)[0]) != config.bot_id:
        raise ConfigurationError("Bot token does not match configured bot ID")
    return SecretStr(raw)
