"""Artifact repository — Bagian 6.1/6.3 MD.

commit_artifact(run token + temp file manifest): hash/size/path tervalidasi;
rename atomic; stale attempt ditolak. Jangan menyimpan file besar sebagai
JSON di task. Success hanya untuk artifact committed dan checks passed.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import UUID, uuid4

from jarvis.orchestration.contracts import MAX_ARTIFACT_SIZE, TaskError
from jarvis.storage.models import Artifact, TaskEvent, TaskRun


def validate_rel_path(rel: str) -> None:
    if not rel or len(rel) > 256 or rel.startswith("/") or ".." in Path(rel).parts:
        raise TaskError("artifact_path_invalid")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def commit_artifact(
    db,
    owner: UUID,
    *,
    task_id: UUID,
    run_id: UUID,
    lease_token: UUID,
    rel_path: str,
    data: bytes,
    media_type: str = "text/plain",
    staging_dir: Path | None = None,
) -> Artifact:
    validate_rel_path(rel_path)
    if len(data) > MAX_ARTIFACT_SIZE:
        raise TaskError("artifact_too_large")
    digest = sha256_bytes(data)
    async with db.tenant(owner) as session:
        run = await session.get(TaskRun, run_id, with_for_update=True)
        if (
            run is None
            or run.owner_id != owner
            or run.task_id != task_id
            or run.lease_token != lease_token
            or run.status not in ("claimed", "running")
        ):
            raise TaskError("stale_run_lease")
        artifact = Artifact(
            id=uuid4(),
            owner_id=owner,
            task_id=task_id,
            run_id=run_id,
            rel_path=rel_path,
            sha256=digest,
            byte_size=len(data),
            media_type=media_type,
            evaluation_status="pending",
        )
        session.add(artifact)
        session.add(
            TaskEvent(
                owner_id=owner,
                task_id=task_id,
                run_id=run_id,
                event_type="artifact.committed",
                payload={"path": rel_path, "sha256": digest, "size": len(data)},
            )
        )
        await session.flush()
        if staging_dir is not None:
            # Persist bytes ke staging dir untuk debugging; atomic rename.
            dest = staging_dir / str(task_id) / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            artifact.object_key = str(dest)
        return artifact


async def mark_evaluated(db, owner: UUID, artifact_id: UUID, status: str) -> None:
    if status not in ("passed", "failed", "needs_human"):
        raise TaskError("artifact_status_invalid")
    async with db.tenant(owner) as session:
        row = await session.get(Artifact, artifact_id, with_for_update=True)
        if row is None or row.owner_id != owner:
            raise TaskError("artifact_not_found")
        row.evaluation_status = status
