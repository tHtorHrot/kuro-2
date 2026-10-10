"""KURO Ultimate contracts — Bagian 6.3 MD.

Kontrak minimal antarmodul. HTTP hanya untuk client/isolated worker
lintas proses; pemanggilan core normal cukup function/protocol Python.

Semua constraints kritis divalidasi code/DB/runtime, bukan prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

# Starter guardrail Bagian 9.1 — tuning proposal, bukan hasil benchmark.
# Agent tidak boleh mengubah limitnya sendiri.
MAX_TASKS_PER_PLAN = 20
MAX_PLAN_DEPTH = 2
MAX_ACTIVE_WORKERS = 2
MAX_PARALLEL_RUNS_PER_TASK = 1
DEFAULT_MAX_REPAIR_PASSES = 1
MAX_PLAN_EDGES = 40
MAX_TITLE_LEN = 120
MAX_GOAL_LEN = 4000
MAX_ARTIFACT_SIZE = 20 * 1024 * 1024  # 20 MiB per artifact


class TaskStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_DEPENDENCY = "waiting_dependency"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    LOST = "lost"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"


TERMINAL_TASK = frozenset(
    {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.UNCERTAIN, TaskStatus.CANCELLED}
)
TERMINAL_RUN = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.LOST,
        RunStatus.CANCELLED,
        RunStatus.UNCERTAIN,
    }
)

# Retry hanya jika semua side effect terkait diketahui aman (Bagian 4.6).
SAFE_RETRY_CLASSES = frozenset({"pre_dispatch", "read_only", "validation_failed"})
NEVER_AUTO_RETRY = frozenset({"external_send", "destructive", "high_impact", "uncertain"})


class TaskError(Exception):
    """Stable local error code; tidak membawa prompt/provider output."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SubmitGoalInput:
    owner_id: UUID
    goal: str
    constraints: dict = field(default_factory=dict)
    client_request_key: str = ""
    cost_ceiling_usd: float = 5.0
    deadline_seconds: int = 3600


@dataclass(frozen=True)
class PlanNode:
    title: str
    role: str
    acceptance: dict
    input_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    cost_ceiling_usd: float = 1.0


@dataclass(frozen=True)
class ValidatedPlan:
    nodes: tuple[PlanNode, ...]
    revision: int = 1
