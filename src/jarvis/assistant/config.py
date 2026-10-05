"""Configuration is operator-owned; neither prompts nor model output may change it."""

import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from jarvis.core.config import ConfigurationError

Money = Annotated[Decimal, Field(ge=0, le=100, max_digits=14, decimal_places=10)]


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    model: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*/[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,160}$")
    provider: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,100}$")

    @model_validator(mode="after")
    def fixed_route(self):
        if self.model.startswith(("openrouter/", "typesafe/")) or ":" in self.model.removesuffix(
            ":free"
        ):
            raise ValueError("A fixed model is required; automatic routers/variants are disabled")
        return self


class AssistantConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    owner_id: UUID
    cloud_privacy: Literal["no_training_zdr"] = "no_training_zdr"
    account_privacy_confirmed: Literal[True]
    free_route: Route
    premium_route: Route | None = None
    premium_mode: Literal["confirm_each_use"] = "confirm_each_use"
    monthly_budget_usd: Money = Decimal("0")
    per_call_budget_usd: Money = Decimal("0")
    max_output_tokens: int = Field(default=512, ge=64, le=1024, strict=True)
    daily_free_calls: int = Field(default=15, ge=1, le=100, strict=True)

    @model_validator(mode="after")
    def budgets(self):
        if self.per_call_budget_usd > self.monthly_budget_usd:
            raise ValueError("Per-call budget must not exceed monthly budget")
        if self.premium_route and self.premium_route == self.free_route:
            raise ValueError("Premium and free routes must differ")
        return self

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    @property
    def premium_enabled(self) -> bool:
        return self.premium_route is not None and self.per_call_budget_usd > 0


def load_assistant_config() -> AssistantConfig:
    try:
        path = Path(os.environ.get("JARVIS_ASSISTANT_CONFIG_FILE", "/run/secrets/assistant_config"))
        raw = path.read_bytes()
        if len(raw) > 8192:
            raise ValueError
        return AssistantConfig.model_validate(json.loads(raw))
    except (OSError, ValueError, ValidationError):
        raise ConfigurationError(
            "Invalid assistant config; run scripts/setup_assistant.py"
        ) from None


def load_router_key() -> SecretStr:
    try:
        path = Path(os.environ.get("JARVIS_OPENROUTER_KEY_FILE", "/run/secrets/openrouter_key"))
        raw = path.read_bytes().decode("ascii").strip("\r\n")
        if not 20 <= len(raw) <= 512 or any(c.isspace() for c in raw):
            raise ValueError
        return SecretStr(raw)
    except (OSError, ValueError):
        raise ConfigurationError("Missing or invalid private OpenRouter key file") from None
