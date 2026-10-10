"""Durable Stage 4 action journal and scheduler primitives."""

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update

from jarvis.identity.service import audit
from jarvis.storage.models import AssistantRequest, AssistantState, ToolAction, ToolGrant, User
from jarvis.tools.contracts import (
    AuthorizationContext,
    AuthorizationDecision,
    ToolProposal,
)
from jarvis.tools.policy import authorize_tool
from jarvis.tools.registry import ToolRegistry

LEASE = timedelta(seconds=90)
MAX_ATTEMPTS = 3


class ActionJournalError(Exception):
    """Stable local error code; never contains arguments or provider output."""


def now_utc() -> datetime:
    return datetime.now(UTC)


def action_fingerprint(
    owner_id: UUID,
    proposal: ToolProposal,
    *,
    version=1,
    due_at=None,
    due_timezone=None,
    latest_dispatch_at=None,
) -> str:
    """Bind authorization to owner + exact tool + canonical JSON arguments."""
    if not isinstance(owner_id, UUID):
        raise TypeError("owner_id must be a UUID")
    try:
        arguments = json.dumps(
            dict(proposal.arguments),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise ActionJournalError("arguments_not_json") from None
    if version == 1:
        payload = f"v1\n{owner_id}\n{proposal.tool_name}\n{arguments}".encode()
    elif version == 2 and due_at is not None and latest_dispatch_at is not None:
        if due_at.tzinfo is None or latest_dispatch_at.tzinfo is None:
            raise ActionJournalError("schedule_requires_timezone")
        schedule = json.dumps(
            [
                due_at.astimezone(UTC).isoformat(),
                due_timezone,
                latest_dispatch_at.astimezone(UTC).isoformat(),
            ],
            separators=(",", ":"),
        )
        payload = f"v2\n{owner_id}\n{proposal.tool_name}\n{arguments}\n{schedule}".encode()
    else:
        raise ActionJournalError("invalid_fingerprint_version")
    return hashlib.sha256(payload).hexdigest()


def spec_fingerprint(spec) -> str:
    payload = [
        spec.name,
        spec.agent,
        spec.effect.value,
        sorted(spec.required_scopes),
        sorted(spec.argument_keys),
        spec.timeout_seconds,
        list(spec.network_targets),
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ClaimedAction:
    id: UUID
    agent: str
    tool_name: str
    effect: str
    arguments: dict = field(repr=False)
    action_fingerprint: str
    lease_token: UUID
    attempt: int
    fingerprint_version: int = 1
    due_at: datetime | None = None
    due_timezone: str | None = None
    latest_dispatch_at: datetime | None = None


class ActionJournal:
    """Owner-scoped durable queue. PostgreSQL is authoritative for execution state."""

    def __init__(self, db, owner: UUID, registry: ToolRegistry, *, executor_binding=None):
        self.db, self.owner, self.registry = db, owner, registry
        self.executor_binding = executor_binding

    async def heartbeat(self):
        agents = {self.registry.get(name).agent for name in self.registry.names()}
        async with self.db.tenant(self.owner) as session:
            await session.execute(
                update(ToolGrant)
                .where(ToolGrant.owner_id == self.owner, ToolGrant.agent.in_(agents))
                .values(last_poll_at=now_utc())
            )

    @asynccontextmanager
    async def transaction(self, session=None):
        if session is not None:
            yield session
        else:
            async with self.db.tenant(self.owner) as own_session:
                yield own_session

    async def create(
        self,
        proposal: ToolProposal,
        context: AuthorizationContext,
        *,
        due_at: datetime | None = None,
        approval_ttl: timedelta = timedelta(minutes=10),
        request_id: UUID | None = None,
        due_timezone: str = "UTC",
        source_key: str | None = None,
        fingerprint_version: int = 1,
        latest_dispatch_at: datetime | None = None,
        session=None,
    ) -> ToolAction:
        try:
            spec = self.registry.get(proposal.tool_name)
        except KeyError:
            raise ActionJournalError("unknown_tool") from None
        if set(proposal.arguments) != set(spec.argument_keys):
            raise ActionJournalError("invalid_arguments")
        if context.approval_granted:
            raise ActionJournalError("approval_requires_journal")
        from jarvis.integrations.calendar.validation import KEYS, validate_arguments

        if spec.name in KEYS:
            try:
                validate_arguments(spec.name, proposal.arguments)
            except ValueError:
                raise ActionJournalError("invalid_arguments") from None
        decision = authorize_tool(spec, context)
        if decision.decision == AuthorizationDecision.DENY:
            raise ActionJournalError(decision.reason)
        if not timedelta(seconds=1) <= approval_ttl <= timedelta(hours=24):
            raise ActionJournalError("invalid_approval_ttl")
        due = due_at or now_utc()
        if due.tzinfo is None:
            raise ActionJournalError("due_at_requires_timezone")
        try:
            ZoneInfo(due_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ActionJournalError("invalid_due_timezone") from None
        if latest_dispatch_at is not None and (
            latest_dispatch_at.tzinfo is None or latest_dispatch_at <= due
        ):
            raise ActionJournalError("invalid_dispatch_window")
        fingerprint = action_fingerprint(
            self.owner,
            proposal,
            version=fingerprint_version,
            due_at=due,
            due_timezone=due_timezone,
            latest_dispatch_at=latest_dispatch_at,
        )
        if source_key is not None and (
            not isinstance(source_key, str) or not 1 <= len(source_key) <= 200
        ):
            raise ActionJournalError("invalid_source_key")
        if len(json.dumps(dict(proposal.arguments), ensure_ascii=False).encode()) > 24000:
            raise ActionJournalError("arguments_too_large")
        awaiting = decision.decision == AuthorizationDecision.REQUIRE_APPROVAL
        row = ToolAction(
            id=uuid4(),
            owner_id=self.owner,
            request_id=request_id,
            agent=spec.agent,
            tool_name=spec.name,
            effect=spec.effect.value,
            arguments=dict(proposal.arguments),
            action_fingerprint=fingerprint,
            status="awaiting_approval" if awaiting else "queued",
            authorization_reason=decision.reason,
            approval_expires_at=now_utc() + approval_ttl if awaiting else None,
            due_at=due.astimezone(UTC),
            due_timezone=due_timezone,
            source_key=source_key,
            spec_fingerprint=spec_fingerprint(spec),
            fingerprint_version=fingerprint_version,
            latest_dispatch_at=latest_dispatch_at,
        )
        async with self.transaction(session) as session:
            grant, reason = await self._authority(session, spec, request_id=request_id)
            if reason:
                raise ActionJournalError(reason)
            if source_key is not None:
                existing = await session.scalar(
                    select(ToolAction).where(
                        ToolAction.owner_id == self.owner, ToolAction.source_key == source_key
                    )
                )
                if existing:
                    if (
                        existing.action_fingerprint != fingerprint
                        or existing.request_id != request_id
                        or existing.due_timezone != due_timezone
                        or (due_at is not None and existing.due_at != due.astimezone(UTC))
                    ):
                        raise ActionJournalError("source_action_conflict")
                    return existing
            row.grant_revision = grant.revision
            session.add(row)
            await session.flush()
            audit(
                session,
                self.owner,
                "tool_action.created",
                row.id,
                request_id=str(request_id) if request_id else None,
            )
        return row

    async def approve(self, action_id: UUID, expected_fingerprint: str, *, session=None) -> None:
        """Approval is valid only for the exact immutable action fingerprint."""
        async with self.transaction(session) as session:
            # Serialize grants and dispatch before locking the action.
            await session.get(User, self.owner, with_for_update=True)
            row = await session.scalar(
                select(ToolAction)
                .where(ToolAction.owner_id == self.owner, ToolAction.id == action_id)
                .with_for_update()
            )
            if not row:
                raise ActionJournalError("action_not_found")
            if row.status != "awaiting_approval":
                raise ActionJournalError("action_not_awaiting_approval")
            if row.approval_expires_at is None or row.approval_expires_at <= now_utc():
                raise ActionJournalError("approval_expired")
            if not expected_fingerprint or expected_fingerprint != row.action_fingerprint:
                raise ActionJournalError("approval_action_mismatch")
            spec = self.registry.get(row.tool_name)
            _, reason = await self._authority(session, spec, row=row)
            if reason:
                raise ActionJournalError(reason)
            row.status = "queued"
            row.approved_at = now_utc()
            row.approval_expires_at = None
            audit(session, self.owner, "tool_action.approved", row.id)

    async def cancel(self, action_id: UUID) -> None:
        async with self.db.tenant(self.owner) as session:
            row = await session.scalar(
                select(ToolAction)
                .where(ToolAction.owner_id == self.owner, ToolAction.id == action_id)
                .with_for_update()
            )
            if not row:
                raise ActionJournalError("action_not_found")
            if row.status not in {"awaiting_approval", "queued", "claimed"}:
                raise ActionJournalError("action_not_cancellable")
            row.status, row.finished_at = "cancelled", now_utc()
            row.lease_token = row.lease_until = None
            audit(session, self.owner, "tool_action.cancelled", row.id)

    async def recover_expired(self) -> int:
        """Pre-dispatch work may retry; post-dispatch expiry is fail-closed uncertain."""
        changed = 0
        async with self.db.tenant(self.owner) as session:
            rows = (
                await session.scalars(
                    select(ToolAction)
                    .where(
                        ToolAction.owner_id == self.owner,
                        ToolAction.status.in_(("claimed", "dispatching")),
                        ToolAction.lease_until < now_utc(),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                if row.status == "claimed":
                    if row.attempts < MAX_ATTEMPTS:
                        row.status = "queued"
                    else:
                        row.status, row.finished_at = "failed", now_utc()
                        row.error_code = "attempts_exhausted_before_dispatch"
                else:
                    row.status, row.finished_at = "uncertain", now_utc()
                row.lease_token = row.lease_until = None
                audit(session, self.owner, f"tool_action.{row.status}", row.id)
                changed += 1
            overdue = (
                await session.scalars(
                    select(ToolAction)
                    .where(
                        ToolAction.owner_id == self.owner,
                        ToolAction.status.in_({"queued", "claimed", "awaiting_approval"}),
                        ToolAction.latest_dispatch_at <= now_utc(),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in overdue:
                row.status, row.finished_at, row.error_code = (
                    "cancelled",
                    now_utc(),
                    "execution_window_expired",
                )
                row.lease_token = row.lease_until = None
                audit(session, self.owner, "tool_action.cancelled", row.id)
                changed += 1
            expired = (
                await session.scalars(
                    select(ToolAction)
                    .where(
                        ToolAction.owner_id == self.owner,
                        ToolAction.status == "awaiting_approval",
                        ToolAction.approval_expires_at <= now_utc(),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in expired:
                row.status, row.finished_at = "cancelled", now_utc()
                row.error_code = "approval_expired"
                audit(session, self.owner, "tool_action.cancelled", row.id)
                changed += 1
        return changed

    async def claim(self) -> ClaimedAction | None:
        async with self.db.tenant(self.owner) as session:
            row = await session.scalar(
                select(ToolAction)
                .where(
                    ToolAction.owner_id == self.owner,
                    ToolAction.status == "queued",
                    ToolAction.due_at <= now_utc(),
                    ToolAction.attempts < MAX_ATTEMPTS,
                )
                .order_by(ToolAction.due_at, ToolAction.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not row:
                return None
            row.status = "claimed"
            row.attempts += 1
            row.lease_token = uuid4()
            row.lease_until = now_utc() + LEASE
            await session.flush()
            return ClaimedAction(
                row.id,
                row.agent,
                row.tool_name,
                row.effect,
                dict(row.arguments),
                row.action_fingerprint,
                row.lease_token,
                row.attempts,
                row.fingerprint_version,
                row.due_at,
                row.due_timezone,
                row.latest_dispatch_at,
            )

    async def reject_claim(self, claimed: ClaimedAction, reason: str) -> None:
        """Fail a claimed action before any external dispatch occurs."""
        if reason not in {
            "tool_definition_changed",
            "action_changed",
            "handler_unavailable",
            "invalid_arguments",
        }:
            raise ValueError("invalid rejection reason")
        async with self.db.tenant(self.owner) as session:
            row = await session.scalar(
                select(ToolAction)
                .where(ToolAction.owner_id == self.owner, ToolAction.id == claimed.id)
                .with_for_update()
            )
            if not self._owns_claim(row, claimed) or row.status != "claimed":
                raise ActionJournalError("stale_action_lease")
            row.status, row.finished_at = "failed", now_utc()
            row.error_code = reason
            row.lease_token = row.lease_until = None
            audit(session, self.owner, "tool_action.failed", row.id)

    async def _authority(self, session, spec, *, row=None, request_id=None):
        user = await session.get(User, self.owner, with_for_update=True, populate_existing=True)
        grant = await session.get(
            ToolGrant, (self.owner, spec.agent), with_for_update=True, populate_existing=True
        )
        if not user or user.status != "active":
            return grant, "owner_inactive"
        if not grant or not grant.enabled or not spec.required_scopes.issubset(grant.scopes):
            return grant, "tool_grant_revoked"
        if self.executor_binding is not None and grant.binding_fingerprint != self.executor_binding:
            return grant, "executor_binding_changed"
        if row and (
            row.grant_revision != grant.revision or row.spec_fingerprint != spec_fingerprint(spec)
        ):
            return grant, "authorization_changed"
        request_id = row.request_id if row else request_id
        if request_id is not None:
            from jarvis.assistant.repository import authorized

            request = await session.get(AssistantRequest, request_id)
            state = await session.get(AssistantState, self.owner)
            from jarvis.orchestration.calendar_tasks import task_valid
            from jarvis.storage.models import CalendarTask

            task = (
                await session.scalar(
                    select(CalendarTask).where(
                        CalendarTask.owner_id == self.owner,
                        CalendarTask.current_action_id == row.id,
                    )
                )
                if row
                else None
            )
            if task and not await task_valid(session, task, state, grant):
                return grant, "source_authorization_changed"
            if (
                not request
                or not state
                or not state.enabled
                or state.frozen
                or request.status in {"cancelled", "failed", "uncertain"}
                or request.revision != state.revision
                or request.config_hash != state.config_hash
                or not await authorized(session, self.owner, request.bot_id)
            ):
                return grant, "source_authorization_changed"
        return grant, None

    async def begin_dispatch(self, claimed: ClaimedAction) -> str | None:
        async with self.db.tenant(self.owner) as session:
            await session.get(User, self.owner, with_for_update=True)
            row = await session.scalar(
                select(ToolAction)
                .where(ToolAction.owner_id == self.owner, ToolAction.id == claimed.id)
                .with_for_update()
            )
            if not self._owns_claim(row, claimed) or row.status != "claimed":
                raise ActionJournalError("stale_action_lease")
            if row.action_fingerprint != claimed.action_fingerprint:
                raise ActionJournalError("action_changed")
            spec = self.registry.get(row.tool_name)
            _, reason = await self._authority(session, spec, row=row)
            if row.due_at > now_utc():
                reason = "execution_not_due"
            if row.latest_dispatch_at is not None and row.latest_dispatch_at <= now_utc():
                reason = "execution_window_expired"
            if reason:
                row.status, row.finished_at, row.error_code = "failed", now_utc(), reason
                row.lease_token = row.lease_until = None
                audit(session, self.owner, "tool_action.failed", row.id)
                return reason
            row.status = "dispatching"
            # A valid provider timeout must fit within this fenced lease.
            row.lease_until = now_utc() + timedelta(seconds=spec.timeout_seconds + 30)
            audit(session, self.owner, "tool_action.dispatching", row.id)
        return None

    async def finish(self, claimed: ClaimedAction, *, outcome: str, result=None) -> None:
        if outcome not in {"succeeded", "failed", "uncertain"}:
            raise ValueError("invalid action outcome")
        if result is not None:
            try:
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
                if not isinstance(result, (dict, list)) or len(encoded.encode()) > 24000:
                    raise ValueError
            except (TypeError, ValueError):
                raise ActionJournalError("invalid_tool_result") from None
        async with self.db.tenant(self.owner) as session:
            row = await session.scalar(
                select(ToolAction)
                .where(ToolAction.owner_id == self.owner, ToolAction.id == claimed.id)
                .with_for_update()
            )
            if not self._owns_claim(row, claimed) or row.status != "dispatching":
                raise ActionJournalError("stale_action_lease")
            row.status, row.finished_at = outcome, now_utc()
            row.result = result
            row.lease_token = row.lease_until = None
            audit(session, self.owner, f"tool_action.{outcome}", row.id)

    @staticmethod
    def _owns_claim(row, claimed: ClaimedAction) -> bool:
        return bool(
            row
            and row.lease_token == claimed.lease_token
            and row.lease_until
            and row.lease_until > now_utc()
        )
