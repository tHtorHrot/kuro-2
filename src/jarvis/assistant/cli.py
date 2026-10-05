import logging

from jarvis.assistant.config import load_assistant_config, load_router_key
from jarvis.assistant.diagnostics import DIAGNOSTICS_VERSION, report_error
from jarvis.assistant.policy import PolicyError
from jarvis.assistant.repository import AssistantRepository, authorized, cancel_pending, owner_state
from jarvis.assistant.router import OpenRouter, RouterError
from jarvis.core.config import ConfigurationError, load_settings
from jarvis.core.logging import configure_logging
from jarvis.identity.service import audit
from jarvis.storage.database import Database


async def operate_assistant(command):
    settings, config = load_settings(), load_assistant_config()
    key = load_router_key() if command in {"assistant-run", "assistant-catalog"} else None
    configure_logging(
        settings.log_level, settings.redacted_values() + ([key.get_secret_value()] if key else [])
    )
    for logger in ("httpx", "httpcore", "langsmith", "langgraph", "langchain"):
        logging.getLogger(logger).disabled = True
    db, router = Database(settings), OpenRouter(key) if key else None
    repo = AssistantRepository(db, config)
    try:
        if not await db.ready():
            raise ConfigurationError("Database not ready; apply stage 3 migration")
        if command == "assistant-run":
            from jarvis.assistant.worker import run_worker

            await run_worker(db, config, router)
            return {"assistant": "stopped"}
        if command == "assistant-catalog":
            try:
                plan = await router.plan(config, "free")
            except (PolicyError, RouterError) as exc:
                code = report_error(exc, phase="catalog", kind="free")
                raise ConfigurationError(
                    f"Free route unavailable; code={code}. No inference sent."
                ) from None
            return {
                "metadata_only": True,
                "inference_sent": False,
                "diagnostics_version": DIAGNOSTICS_VERSION,
                "free_plan": plan,
            }
        if command in {"assistant-status", "assistant-health"}:
            status = await repo.status()
            status["diagnostics_version"] = DIAGNOSTICS_VERSION
            if command == "assistant-health" and not (
                status["worker_recent"] and status["config_matches"]
            ):
                raise ConfigurationError("Assistant has no recent heartbeat or config mismatch")
            return status
        if command not in {"assistant-enable", "assistant-disable"}:
            raise ConfigurationError("Unsupported assistant command")
        async with db.tenant(config.owner_id) as session:
            state = await owner_state(session, config.owner_id)
            if not state or state.config_hash != config.fingerprint:
                raise ConfigurationError(
                    "Start/restart assistant worker with matching config first"
                )
            if command == "assistant-enable":
                if state.frozen:
                    raise ConfigurationError(
                        "Assistant frozen after unverifiable cost/route; reconcile "
                        "ledger before operator repair"
                    )
                if not await authorized(session, config.owner_id):
                    raise ConfigurationError("Active paired owner required")
            await cancel_pending(session, state)
            state.enabled = command == "assistant-enable"
            audit(
                session,
                config.owner_id,
                "assistant.enabled" if state.enabled else "assistant.disabled",
                None,
            )
            return {"assistant_enabled": state.enabled, "premium_mode": "confirm_each_use"}
    finally:
        if router:
            await router.close()
        await db.close()
