"""JSON logging with a small field allowlist and no exception payload capture."""

import json
import logging
import re
from datetime import UTC, datetime

SAFE_EXTRAS = ("event", "request_id", "route", "method", "status", "duration_ms", "error_type")


class SafeJsonFormatter(logging.Formatter):
    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self.secrets = sorted((x for x in secrets or [] if x), key=len, reverse=True)

    def redact(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
        value = re.sub(r"jv[pt]1\.[A-Za-z0-9_.-]+", "[REDACTED_TOKEN]", value)
        value = re.sub(r"https?://[^\s\"']+", "[REDACTED_URL]", value)
        value = re.sub(r"postgresql[^\s\"']*://[^\s\"']+", "[REDACTED_DSN]", value)
        return value

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.redact(record.getMessage()),
        }
        for key in SAFE_EXTRAS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = self.redact(str(value)) if isinstance(value, str) else value
        if record.exc_info and record.exc_info[0]:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, secrets: list[str]) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeJsonFormatter(secrets))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
