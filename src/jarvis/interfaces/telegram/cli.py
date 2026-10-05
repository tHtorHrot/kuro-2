import logging

from sqlalchemy import select

from jarvis.core.config import ConfigurationError, load_settings
from jarvis.core.logging import configure_logging
from jarvis.identity.service import audit, create_pairing_code
from jarvis.interfaces.telegram.client import TelegramClient
from jarvis.interfaces.telegram.config import load_bot_token, load_telegram_config
from jarvis.interfaces.telegram.repository import TelegramRepository
from jarvis.interfaces.telegram.worker import run_worker
from jarvis.storage.database import Database
from jarvis.storage.models import ExternalIdentity


async def operate_telegram(command: str) -> dict:
    if command not in {
        "telegram-run",
        "telegram-status",
        "telegram-health",
        "telegram-pair",
        "telegram-enable",
        "telegram-disable",
    }:
        raise ConfigurationError("Unsupported Telegram operation")
    settings, config = load_settings(), load_telegram_config()
    secrets = settings.redacted_values()
    token = load_bot_token(config) if command == "telegram-run" else None
    if token:
        secrets.append(token.get_secret_value())
    configure_logging(settings.log_level, secrets)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    db = Database(settings)
    client = TelegramClient(token) if token else None
    try:
        if not await db.ready():
            raise ConfigurationError("Database is not ready; apply the stage 2A migration")
        if command == "telegram-run":
            await run_worker(db, config, client)
            return {"telegram": "stopped"}
        repo = TelegramRepository(db, config)
        if command in ("telegram-status", "telegram-health"):
            status = await repo.status()
            if command == "telegram-health" and not status["worker_recently_polled"]:
                raise ConfigurationError("Telegram worker has no recent successful poll")
            return status
        async with db.tenant(config.owner_id) as session:
            identity = await session.scalar(
                select(ExternalIdentity)
                .where(ExternalIdentity.owner_id == config.owner_id)
                .with_for_update()
            )
            if command == "telegram-pair":
                if identity is not None:
                    raise ConfigurationError("Identity already exists; use status/enable/disable")
                raw = await create_pairing_code(
                    session, config.owner_id, settings.token_pepper, config.sender_id
                )
                return {
                    "pairing_command": "/pair " + raw.get_secret_value(),
                    "expires_in_seconds": 600,
                    "notice": "Paste only into your own bot's private chat.",
                }
            if identity is None or identity.external_user_id != config.sender_id:
                raise ConfigurationError("Matching Telegram identity not found")
            identity.enabled = command == "telegram-enable"
            audit(
                session,
                config.owner_id,
                "telegram.enabled" if identity.enabled else "telegram.disabled",
                identity.id,
            )
            return {"telegram_identity_enabled": identity.enabled}
    finally:
        if client:
            await client.close()
        await db.close()
