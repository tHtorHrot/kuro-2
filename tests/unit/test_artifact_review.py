"""Review planner: hanya artifact passed milik task yang lolos (offline)."""

from types import SimpleNamespace
from uuid import uuid4

from jarvis.artifacts.repository import artifact_accepted

OWNER, TASK = uuid4(), uuid4()


def art(**over):
    base = {"owner_id": OWNER, "task_id": TASK, "evaluation_status": "passed"}
    return SimpleNamespace(**{**base, **over})


def test_accepts_passed_own_task_artifact():
    assert artifact_accepted(art(), OWNER, TASK)


def test_rejects_missing_foreign_pending_failed_needs_human():
    other = uuid4()
    assert not artifact_accepted(None, OWNER, TASK)
    assert not artifact_accepted(art(owner_id=other), OWNER, TASK)
    assert not artifact_accepted(art(task_id=other), OWNER, TASK)
    for status in ("pending", "failed", "needs_human", "unknown"):
        assert not artifact_accepted(art(evaluation_status=status), OWNER, TASK)
