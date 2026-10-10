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

from jarvis.automation.service import AutomationError
from jarvis.core.config import ConfigurationError, load_settings
from jarvis.core.errors import UnsafeDatabaseRole
from jarvis.core.logging import configure_logging
from jarvis.identity.service import ALL_SCOPES, audit, create_pairing_code, issue_api_token
from jarvis.orchestration.contracts import TaskError
from jarvis.orchestration.llm_planner import PlanProposalError
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
    once = sub.add_parser(
        "tasks-run-once",
        help="Intake queued read-only tasks: claim, write intake record artifact, finish",
    )
    once.add_argument("--owner-id", type=UUID, required=True)
    once.add_argument("--max", type=int, default=3)
    once.add_argument("--worker", default="cli-once")
    loop = sub.add_parser(
        "tasks-loop", help="Run intake batches forever until stopped (task worker)"
    )
    loop.add_argument("--owner-id", type=UUID, required=True)
    loop.add_argument("--interval", type=int, default=30)
    loop.add_argument("--max", type=int, default=3)
    loop.add_argument("--worker", default="task-loop")
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
    monitor = sub.add_parser("ops-monitor", help="Read-only owner-scoped operational snapshot")
    monitor.add_argument("--owner-id", type=UUID, required=True)
    prune = sub.add_parser("tasks-prune", help="Dry-run (default) or batch-prune old task events")
    prune.add_argument("--owner-id", type=UUID, required=True)
    prune.add_argument("--days", type=int, default=90)
    prune.add_argument("--limit", type=int, default=500)
    prune.add_argument("--apply", action="store_true")
    create = sub.add_parser("automation-create", help="Create a recurring goal definition")
    create.add_argument("--owner-id", type=UUID, required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--timezone", default="Asia/Jakarta")
    create.add_argument("--rrule", required=True)
    create.add_argument("--goal", required=True)
    sub.add_parser("automation-tick").add_argument("--owner-id", type=UUID, required=True)
    ticker = sub.add_parser("automation-loop", help="Run automation tick forever until stopped")
    ticker.add_argument("--owner-id", type=UUID, required=True)
    ticker.add_argument("--interval", type=int, default=300)
    preview = sub.add_parser(
        "tasks-plan-preview",
        help="Print planner prompt for a goal; optionally validate a proposal file",
    )
    preview.add_argument("--goal", required=True)
    preview.add_argument("--proposal-file", default=None)
    auto = sub.add_parser(
        "tasks-plan-auto", help="Propose a validated plan for a queued root task (free route)"
    )
    auto.add_argument("--owner-id", type=UUID, required=True)
    auto.add_argument("--task-id", type=UUID, required=True)
    auto.add_argument("--worker", default="planner-auto")
    return p


async def operate(args: argparse.Namespace) -> dict:
    settings = load_settings()
    configure_logging(settings.log_level, settings.redacted_values())
    db = Database(settings)
    try:
        await db.verify_runtime_role()
        if args.command == "ops-monitor":
            from jarvis.operations.monitor import snapshot

            return await snapshot(db, args.owner_id)
        if args.command == "tasks-prune":
            from jarvis.operations.task_retention import prune_events

            return await prune_events(
                db,
                args.owner_id,
                older_than_days=args.days,
                limit=args.limit,
                apply=args.apply,
            )
        if args.command == "automation-create":
            from jarvis.automation.service import create_definition

            row = await create_definition(
                db,
                args.owner_id,
                title=args.title,
                timezone=args.timezone,
                rrule=args.rrule,
                goal_template=args.goal,
            )
            return {"definition_id": str(row.id), "rrule": row.rrule}
        if args.command == "automation-tick":
            from jarvis.automation.service import tick

            items = await tick(db, args.owner_id)
            return {"launched": len(items), "items": items}
        if args.command == "tasks-plan-preview":
            from pathlib import Path

            from jarvis.orchestration.llm_planner import build_plan_prompt, parse_plan_response
            from jarvis.orchestration.planner import validate_plan

            prompt = build_plan_prompt(goal=args.goal)
            if not args.proposal_file:
                return {"prompt": prompt, "validated": False}
            if args.proposal_file == "-":
                text = await asyncio.to_thread(sys.stdin.read)
            else:
                text = await asyncio.to_thread(Path(args.proposal_file).read_text, encoding="utf-8")
            nodes = parse_plan_response(text)
            plan = validate_plan(nodes)
            return {
                "prompt_chars": len(prompt),
                "validated": True,
                "tasks": len(plan.nodes),
                "revision": plan.revision,
            }
        if args.command == "tasks-plan-auto":
            from jarvis.assistant.config import load_assistant_config, load_router_key
            from jarvis.assistant.router import OpenRouter
            from jarvis.orchestration.llm_planner import propose_plan

            config = load_assistant_config()
            router = OpenRouter(load_router_key())
            try:
                endpoint = await router.plan(config, "free")
                return await propose_plan(
                    db,
                    args.owner_id,
                    args.task_id,
                    router=router,
                    endpoint_plan=endpoint,
                    worker=args.worker,
                )
            finally:
                await router.close()
        if args.command == "automation-loop":
            import signal

            from jarvis.automation.service import tick

            if not 60 <= args.interval <= 3600:
                raise ValueError("interval must be 60..3600 seconds")
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(signum, stop.set)
                except NotImplementedError:
                    pass
            rounds, total = 0, 0
            while not stop.is_set():
                items = await tick(db, args.owner_id)
                rounds += 1
                total += len(items)
                print(
                    json.dumps({"automation_loop": "tick", "round": rounds, "launched": total}),
                    flush=True,
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=args.interval)
                except TimeoutError:
                    pass
            return {"automation_loop": "stopped", "rounds": rounds, "launched": total}
        if args.command == "doctor":
            if not await db.ready():
                raise ConfigurationError(
                    "Schema or RLS not ready; run migrations and check role grants"
                )
            return {"database": "ready", "rls": "enabled_and_forced", "stage": "4"}
        if args.command == "tasks-run-once":
            from jarvis.orchestration.intake import process_intake_batch

            if not 1 <= args.max <= 10:
                raise ValueError("max must be 1..10")
            if not args.worker or len(args.worker) > 80:
                raise ValueError("worker name must be 1..80 characters")
            items = await process_intake_batch(db, args.owner_id, args.worker, args.max)
            return {"processed": len(items), "items": items}
        if args.command == "tasks-loop":
            import signal

            from jarvis.orchestration.intake import process_intake_batch

            if not 10 <= args.interval <= 300:
                raise ValueError("interval must be 10..300 seconds")
            if not 1 <= args.max <= 10:
                raise ValueError("max must be 1..10")
            if not args.worker or len(args.worker) > 80:
                raise ValueError("worker name must be 1..80 characters")
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(signum, stop.set)
                except NotImplementedError:
                    pass
            batches, total = 0, 0
            while not stop.is_set():
                items = await process_intake_batch(db, args.owner_id, args.worker, args.max)
                batches += 1
                total += len(items)
                print(
                    json.dumps({"tasks_loop": "batch", "batch": batches, "processed": total}),
                    flush=True,
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=args.interval)
                except TimeoutError:
                    pass
            return {"tasks_loop": "stopped", "batches": batches, "processed": total}
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
    except (AutomationError, TaskError, PlanProposalError) as exc:
        print(f"Task error: {exc.code}", file=sys.stderr)
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
