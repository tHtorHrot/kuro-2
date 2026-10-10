"""Recurring automation — definisi terpisah dari run (pola AO yang diadopsi).

Subset jadwal stdlib tanpa dependensi baru: FREQ=DAILY atau FREQ=WEEKLY
dengan BYDAY/BYHOUR/BYMINUTE tunggal. RRULE penuh ditolak eksplisit sampai
parser yang layak tersedia. Catch-up bounded per tick; occurrence_key unik
mencegah ganda saat restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
CATCHUP_WINDOW = timedelta(hours=24)
MAX_LAUNCH_PER_TICK = 3


class AutomationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Schedule:
    freq: str
    days: frozenset[int]
    hour: int
    minute: int
    timezone: str


def parse_schedule(rrule: str, timezone: str) -> Schedule:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise AutomationError("automation_timezone_invalid") from None
    if not isinstance(rrule, str) or len(rrule) > 256:
        raise AutomationError("automation_rrule_invalid")
    parts: dict[str, str] = {}
    for chunk in rrule.split(";"):
        if "=" not in chunk:
            raise AutomationError("automation_rrule_invalid")
        key, _, value = chunk.partition("=")
        parts[key.strip().upper()] = value.strip().upper()
    freq = parts.get("FREQ", "")
    if freq not in ("DAILY", "WEEKLY"):
        raise AutomationError("automation_freq_unsupported")
    try:
        hour = int(parts.get("BYHOUR", ""))
        minute = int(parts.get("BYMINUTE", ""))
    except ValueError:
        raise AutomationError("automation_time_invalid") from None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise AutomationError("automation_time_invalid")
    if freq == "DAILY":
        if "BYDAY" in parts:
            raise AutomationError("automation_rrule_invalid")
        days = frozenset(range(7))
    else:
        raw_days = [d.strip() for d in parts.get("BYDAY", "").split(",") if d.strip()]
        if not raw_days or any(d not in WEEKDAYS for d in raw_days):
            raise AutomationError("automation_byday_invalid")
        days = frozenset(WEEKDAYS[d] for d in raw_days)
    return Schedule(freq, days, hour, minute, timezone)


def occurrences_between(
    spec: Schedule, since: datetime, until: datetime, *, limit: int = 10
) -> list[datetime]:
    """Occurrence lokal zona definition, dikembalikan sebagai UTC aware."""
    if limit < 1 or limit > 31:
        raise AutomationError("automation_limit_invalid")
    zone = ZoneInfo(spec.timezone)
    start = since.astimezone(zone).replace(tzinfo=None)
    end = until.astimezone(zone).replace(tzinfo=None)
    if end < start:
        return []
    out: list[datetime] = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    last = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= last and len(out) < limit:
        candidate = day.replace(hour=spec.hour, minute=spec.minute)
        if (
            candidate.weekday() in spec.days
            and start <= candidate <= end
            and candidate >= (since - timedelta(seconds=1)).astimezone(zone).replace(tzinfo=None)
        ):
            out.append(candidate.replace(tzinfo=zone).astimezone(UTC))
        day += timedelta(days=1)
    return out


async def create_definition(
    db, owner: UUID, *, title: str, timezone: str, rrule: str, goal_template: str
):
    from jarvis.storage.models import AutomationDefinition

    if not title or len(title) > 120:
        raise AutomationError("automation_title_invalid")
    if not goal_template or len(goal_template) > 2000:
        raise AutomationError("automation_goal_invalid")
    spec = parse_schedule(rrule, timezone)
    async with db.tenant(owner) as session:
        row = AutomationDefinition(
            id=uuid4(),
            owner_id=owner,
            title=title.strip(),
            timezone=spec.timezone,
            rrule=rrule.strip().upper(),
            goal_template=goal_template.strip(),
            enabled=True,
        )
        session.add(row)
        await session.flush()
        return row


async def tick(db, owner: UUID, *, now: datetime | None = None) -> list[dict]:
    """Launch occurrence jatuh tempo; idempotent via occurrence_key unik.

    Tiga transaksi pendek per occurrence (claim run, submit goal, link task)
    agar tidak menahan lock saat inference/IO lain berjalan.
    """
    from jarvis.orchestration.contracts import SubmitGoalInput
    from jarvis.orchestration.task_manager import submit_goal
    from jarvis.storage.models import AutomationDefinition, AutomationRun

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise AutomationError("automation_now_naive")
    due_items: list[tuple[UUID, UUID, datetime, str]] = []
    async with db.tenant(owner) as session:
        definitions = (
            await session.scalars(
                select(AutomationDefinition).where(
                    AutomationDefinition.owner_id == owner,
                    AutomationDefinition.enabled.is_(True),
                )
            )
        ).all()
        for definition in definitions:
            spec = parse_schedule(definition.rrule, definition.timezone)
            latest = await session.scalar(
                select(func.max(AutomationRun.occurrence_at)).where(
                    AutomationRun.owner_id == owner,
                    AutomationRun.definition_id == definition.id,
                )
            )
            since = max(latest, moment - CATCHUP_WINDOW) if latest else moment - CATCHUP_WINDOW
            due = occurrences_between(spec, since, moment, limit=MAX_LAUNCH_PER_TICK + 5)
            # Lewati occurrence yang sama dengan batas bawah (sudah dihitung).
            due = [d for d in due if latest is None or d > latest][:MAX_LAUNCH_PER_TICK]
            for occurrence in due:
                key = f"{definition.id.hex}:{occurrence.strftime('%Y%m%dT%H%M')}"
                exists = await session.scalar(
                    select(AutomationRun.id).where(
                        AutomationRun.owner_id == owner, AutomationRun.occurrence_key == key
                    )
                )
                if exists is not None:
                    continue
                run = AutomationRun(
                    id=uuid4(),
                    owner_id=owner,
                    definition_id=definition.id,
                    occurrence_at=occurrence,
                    occurrence_key=key,
                    task_id=None,
                    status="launched",
                )
                session.add(run)
                await session.flush()
                due_items.append((definition.id, run.id, occurrence, definition.goal_template))
    launched: list[dict] = []
    for definition_id, run_id, occurrence, template in due_items:
        task = await submit_goal(
            db,
            SubmitGoalInput(
                owner_id=owner,
                goal=f"{template}\nJadwal: {occurrence.isoformat()}",
                client_request_key=f"auto:{definition_id.hex}:{occurrence.strftime('%Y%m%dT%H%M')}",
            ),
        )
        async with db.tenant(owner) as session:
            run = await session.get(AutomationRun, run_id)
            if run is not None and run.owner_id == owner:
                run.task_id = task.id
        launched.append(
            {
                "definition_id": str(definition_id),
                "occurrence": occurrence.isoformat(),
                "task_id": str(task.id),
            }
        )
    return launched
