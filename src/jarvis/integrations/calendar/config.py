"""Deployment-only Calendar credential loading."""

import hashlib
import json
import os
from dataclasses import dataclass

from pydantic import SecretStr

from jarvis.core.config import ConfigurationError, read_secret


@dataclass(frozen=True)
class CalendarSecrets:
    client_id: SecretStr
    client_secret: SecretStr
    refresh_token: SecretStr
    calendar_id: str = "primary"


def calendar_binding(client_id, refresh_token, calendar_id):
    """Opaque executor identity; queued work cannot silently move to another account."""
    values = [client_id.get_secret_value(), refresh_token.get_secret_value(), calendar_id]
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def load_calendar_secrets() -> CalendarSecrets:
    calendar_id = os.getenv("JARVIS_GOOGLE_CALENDAR_ID", "primary").strip()
    if not calendar_id or len(calendar_id) > 512 or any(c in calendar_id for c in "\r\n\x00"):
        raise ConfigurationError("Invalid JARVIS_GOOGLE_CALENDAR_ID")
    return CalendarSecrets(
        SecretStr(read_secret("JARVIS_GOOGLE_CLIENT_ID")),
        SecretStr(read_secret("JARVIS_GOOGLE_CLIENT_SECRET")),
        SecretStr(read_secret("JARVIS_GOOGLE_REFRESH_TOKEN")),
        calendar_id,
    )
