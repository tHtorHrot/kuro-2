"""Native: POST complete menegakkan review artifact (DB + app nyata)."""

import pytest
from httpx import ASGITransport, AsyncClient
from test_tasks import goal, owner

from jarvis.api.dependencies import principal
from jarvis.identity.service import Principal
from jarvis.main import create_app
from jarvis.orchestration.task_manager import submit_goal
from jarvis.storage.models import Artifact

pytestmark = pytest.mark.integration


async def seed_task(db, oid, key="rev-1"):
    root = await submit_goal(db, goal(oid, "tugas review", key=key))
    return root


async def seed_artifact(db, oid, task_id, status="passed", owner=None):
    from uuid import uuid4

    async with db.tenant(owner or oid) as session:
        row = Artifact(
            id=uuid4(),
            owner_id=owner or oid,
            task_id=task_id,
            rel_path="hasil.txt",
            sha256="a" * 64,
            byte_size=5,
            evaluation_status=status,
        )
        session.add(row)
        await session.flush()
        return row.id


async def app_client(db, settings, oid):
    app = create_app(settings, db)
    app.dependency_overrides[principal] = lambda: Principal(
        oid, oid, frozenset({"tasks:read", "tasks:write"})
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def test_complete_accepts_only_passed_own_artifacts(test_db, settings):
    oid = await owner(test_db)
    task = await seed_task(test_db, oid)
    good = await seed_artifact(test_db, oid, task.id, "passed")
    stale = await seed_artifact(test_db, oid, task.id, "pending")
    bad = await seed_artifact(test_db, oid, task.id, "failed")
    other_task = await seed_task(test_db, oid, key="rev-2")
    foreign = await seed_artifact(test_db, oid, other_task.id, "passed")
    ghost = "00000000-0000-4000-8000-000000000099"

    async with await app_client(test_db, settings, oid) as client:
        ok = await client.post(
            f"/api/v1/tasks/{task.id}/complete",
            json={"status": "succeeded", "artifact_ids": [str(good)]},
        )
        assert ok.status_code == 200, ok.text
        for bad_ids, name in (
            ([str(stale)], "pending"),
            ([str(bad)], "failed"),
            ([str(foreign)], "foreign-task"),
            ([ghost], "ghost"),
            (["bukan-uuid"], "malformed"),
            ([str(good), str(stale)], "mixed"),
        ):
            response = await client.post(
                f"/api/v1/tasks/{task.id}/complete",
                json={"status": "succeeded", "artifact_ids": bad_ids},
            )
            assert response.status_code == 422, (name, response.text)
            assert response.json()["code"] == "artifact_not_accepted"
        missing = await client.post(
            f"/api/v1/tasks/{task.id}/complete", json={"status": "succeeded"}
        )
        assert missing.status_code == 422
        assert missing.json()["code"] == "artifact_required"
