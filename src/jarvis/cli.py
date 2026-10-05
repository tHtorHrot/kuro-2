"""Trusted operator commands. Never expose this CLI as an LLM tool."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import SQLAlchemyError

from jarvis.core.config import ConfigurationError, load_settings
from jarvis.core.errors import UnsafeDatabaseRole
from jarvis.core.logging import configure_logging
from jarvis.identity.service import ALL_SCOPES, audit, create_pairing_code, issue_api_token
from jarvis.storage.database import Database
from jarvis.storage.models import ApiToken, User


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Jarvis trusted-operator CLI")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Apply migrations with separate migrator credential")
    sub.add_parser("doctor", help="Check runtime role, schema revision and RLS")
    for name in ("run", "status", "health", "pair", "enable", "disable"):
        sub.add_parser("telegram-" + name, help="Private Telegram adapter operation")
    for name in ("run", "status", "health", "catalog", "enable", "disable"):
        sub.add_parser("assistant-" + name, help="Owner-private inference and memory operation")
    for name in ("run", "status", "health", "check", "model-download"):
        sub.add_parser("knowledge-" + name, help="Local document knowledge operation")
    tool_status = sub.add_parser("tools-status", help="Stage 4 owner action summary")
    tool_status.add_argument("--owner-id", type=UUID, required=True)
    grant = sub.add_parser("tools-grant", help="Set or revoke durable Calendar scopes")
    grant.add_argument("--owner-id", type=UUID, required=True)
    grant.add_argument(
        "--scope",
        action="append",
        choices=["calendar:read", "calendar:write", "calendar:send"],
        default=[],
    )
    grant.add_argument("--disable", action="store_true")
    for name in ("approve", "cancel", "reconcile"):
        q = sub.add_parser("tools-" + name)
        q.add_argument("--owner-id", type=UUID, required=True)
        q.add_argument("--action-id", type=UUID, required=True)
        if name == "approve":
            q.add_argument("--fingerprint", required=True)
    for name in ("run", "once", "health"):
        q = sub.add_parser("scheduler-" + name)
        q.add_argument("--owner-id", type=UUID, required=True)
    sub.add_parser("documents-list")
    for name in ("info", "delete", "retry"):
        sub.add_parser("documents-" + name).add_argument("document_id", type=UUID)
    doc = sub.add_parser("documents-import", help="Import bounded bytes from stdin")
    doc.add_argument("--filename", required=True)
    doc.add_argument("--data-class", choices=["private", "restricted"], default="private")
    doc.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    owner = sub.add_parser("owner-create", help="Create owner and print first token once")
    owner.add_argument("--name", required=True)
    owner.add_argument("--timezone", default="Asia/Jakarta")
    for name in ("token-issue", "token-revoke", "pairing-create", "owner-set-status"):
        command_parser = sub.add_parser(name)
        command_parser.add_argument("--owner-id", type=UUID, required=True)
        if name == "token-issue":
            command_parser.add_argument("--label", default="operator-issued")
            command_parser.add_argument("--days", type=int, default=30)
            command_parser.add_argument(
                "--scope", action="append", choices=sorted(ALL_SCOPES), required=True
            )
        elif name == "token-revoke":
            command_parser.add_argument("--token-id", type=UUID, required=True)
        elif name == "pairing-create":
            command_parser.add_argument("--telegram-user-id", type=int, required=True)
        else:
            command_parser.add_argument("--status", choices=["active", "suspended"], required=True)
    return p


async def operate(args: argparse.Namespace) -> dict:
    settings = load_settings()
    configure_logging(settings.log_level, settings.redacted_values())
    db = Database(settings)
    try:
        await db.verify_runtime_role()
        if args.command == "doctor":
            if not await db.ready():
                raise ConfigurationError(
                    "Schema or RLS not ready; run migrations and check role grants"
                )
            return {"database": "ready", "rls": "enabled_and_forced", "stage": "4"}
        if args.command == "owner-create":
            if not 1 <= len(args.name) <= 100:
                raise ValueError("Name must be 1..100 characters")
            try:
                ZoneInfo(args.timezone)
            except ZoneInfoNotFoundError:
                raise ValueError("Unknown IANA timezone") from None
            owner_id = uuid4()
            async with db.tenant(owner_id) as session:
                session.add(
                    User(
                        id=owner_id, display_name=args.name, timezone=args.timezone, status="active"
                    )
                )
                await session.flush()
                token, raw = await issue_api_token(
                    session, owner_id, settings.token_pepper, "initial-owner", ALL_SCOPES
                )
                audit(session, owner_id, "owner.created", owner_id)
            return {
                "owner_id": str(owner_id),
                "token_id": str(token.id),
                "token": raw.get_secret_value(),
                "expires_at": token.expires_at.isoformat(),
                "notice": "Save this token securely. It will not be displayed again.",
            }
        async with db.tenant(args.owner_id) as session:
            if args.command == "token-issue":
                token, raw = await issue_api_token(
                    session,
                    args.owner_id,
                    settings.token_pepper,
                    args.label,
                    set(args.scope),
                    args.days,
                )
                return {
                    "token_id": str(token.id),
                    "token": raw.get_secret_value(),
                    "expires_at": token.expires_at.isoformat(),
                }
            if args.command == "pairing-create":
                raw = await create_pairing_code(
                    session, args.owner_id, settings.token_pepper, args.telegram_user_id
                )
                return {
                    "pairing_code": raw.get_secret_value(),
                    "expires_in_seconds": 600,
                    "notice": "Paste only into the configured bot's private chat.",
                }
            if args.command == "token-revoke":
                token = await session.get(ApiToken, args.token_id)
                if token is None:
                    raise ValueError("Token not found for this owner")
                token.revoked_at = datetime.now(UTC)
                audit(session, args.owner_id, "token.revoked", token.id)
                return {"revoked": str(token.id)}
            if args.command == "owner-set-status":
                user = await session.get(User, args.owner_id)
                if user is None:
                    raise ValueError("Owner not found")
                user.status = args.status
                audit(session, args.owner_id, "owner." + args.status, user.id)
                return {"owner_id": str(user.id), "status": user.status}
        raise ValueError("Unsupported command")
    finally:
        await db.close()


def main() -> None:
    args = parser().parse_args()
    from jarvis.interfaces.telegram.client import TelegramError
    from jarvis.interfaces.telegram.worker import LostPollerLock

    try:
        if args.command.startswith(("knowledge-", "documents-")):
            from jarvis.knowledge.cli import operate_knowledge

            print(json.dumps(asyncio.run(operate_knowledge(args)), ensure_ascii=False, default=str))
        elif args.command.startswith("assistant-"):
            from jarvis.assistant.cli import operate_assistant

            print(json.dumps(asyncio.run(operate_assistant(args.command))))
        elif args.command.startswith("telegram-"):
            from jarvis.interfaces.telegram.cli import operate_telegram

            print(json.dumps(asyncio.run(operate_telegram(args.command))))
        elif args.command.startswith("tools-") or args.command.startswith("scheduler-"):
            from jarvis.tools.operator import (
                action_status,
                approve,
                cancel,
                grant_calendar,
                reconcile,
                run_scheduler,
            )

            if args.command == "tools-status":
                result = asyncio.run(action_status(args.owner_id))
            elif args.command == "tools-grant":
                result = asyncio.run(
                    grant_calendar(args.owner_id, frozenset(args.scope), enabled=not args.disable)
                )
            elif args.command == "tools-approve":
                result = asyncio.run(approve(args.owner_id, args.action_id, args.fingerprint))
            elif args.command == "tools-cancel":
                result = asyncio.run(cancel(args.owner_id, args.action_id))
            elif args.command == "tools-reconcile":
                result = asyncio.run(reconcile(args.owner_id, args.action_id))
            elif args.command == "scheduler-health":
                result = asyncio.run(action_status(args.owner_id))
                if not result["worker_recent"]:
                    raise ConfigurationError("Scheduler heartbeat is stale or missing")
            else:
                result = asyncio.run(
                    run_scheduler(args.owner_id, once=args.command == "scheduler-once")
                )
            print(json.dumps(result, ensure_ascii=False))
        elif args.command == "migrate":
            # No runtime pepper or application URL is needed by the migrator process.
            command.upgrade(Config("alembic.ini"), "head")
            print(json.dumps({"migrations": "applied"}))
        else:
            print(json.dumps(asyncio.run(operate(args)), ensure_ascii=False))
    except (ConfigurationError, UnsafeDatabaseRole, ValueError) as exc:
        print(f"Configuration/command error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except SQLAlchemyError:
        print("Database operation failed. Check readiness, grants and migrations.", file=sys.stderr)
        raise SystemExit(3) from None
    except (TelegramError, LostPollerLock) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(4) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception:
        # An unexpected transport/library exception must not dump token-bearing URLs.
        print("Operation failed unexpectedly; check safe logs and run doctor.", file=sys.stderr)
        raise SystemExit(5) from None


if __name__ == "__main__":
    main()
