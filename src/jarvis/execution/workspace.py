"""Workspace per coding task/run — Bagian 5/6.1 MD.

Git worktree untuk repo; managed directory untuk Data/report.
Satu workspace per task. Guard dirty workspace: verify dirty state;
quarantine/preserve sebelum remove. Worktree saja bukan sandbox.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

WORKSPACE_ROOT_NAME = "kuro-workspaces"


class WorkspaceError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Workspace:
    owner_id: UUID
    task_id: UUID
    run_id: UUID
    path: Path


def workspace_root(base: Path) -> Path:
    return base / WORKSPACE_ROOT_NAME


def resolve_inside(root: Path, rel: str) -> Path:
    """Runtime menolak path di luar workspace/symlink escape (bukan cuma prompt)."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        raise WorkspaceError("path_outside_workspace")
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise WorkspaceError("path_outside_workspace")
    return candidate


def create_managed(base: Path, *, owner_id: UUID, task_id: UUID, run_id: UUID) -> Workspace:
    root = workspace_root(base) / str(owner_id) / str(task_id) / str(run_id)
    root.mkdir(parents=True, exist_ok=False)
    return Workspace(owner_id, task_id, run_id, root)


def create_worktree(
    repo: Path, base: Path, *, owner_id: UUID, task_id: UUID, run_id: UUID, branch: str
) -> Workspace:
    """Git worktree memisahkan checkout. Caller wajib verify branch aman."""
    if not branch or len(branch) > 128 or any(c in branch for c in " \t\n;|&$"):
        raise WorkspaceError("branch_invalid")
    ws = create_managed(base, owner_id=owner_id, task_id=task_id, run_id=run_id)
    try:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", str(ws.path), "-b", branch],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except Exception:
        shutil.rmtree(ws.path, ignore_errors=True)
        raise WorkspaceError("worktree_failed") from None
    return ws


def is_dirty(path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def destroy(ws: Workspace, *, quarantine_base: Path | None = None) -> str:
    """Jangan membuang pekerjaan sebelum terbukti aman: quarantine dulu bila dirty."""
    if is_dirty(ws.path) if (ws.path / ".git").exists() or True else False:
        # Untuk managed dir: anggap dirty bila ada file user.
        try:
            has_files = any(ws.path.iterdir())
        except FileNotFoundError:
            return "gone"
        if has_files and quarantine_base is not None:
            dest = quarantine_base / f"{ws.task_id}-{ws.run_id}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ws.path), str(dest))
            return "quarantined"
    # Coba git worktree remove bila berasal dari worktree, abaikan bila gagal.
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(ws.path)], capture_output=True, timeout=60
        )
    except Exception:
        pass
    shutil.rmtree(ws.path, ignore_errors=True)
    return "removed"


def write_file(ws: Workspace, rel: str, data: bytes, *, max_bytes: int = 5 * 1024 * 1024) -> Path:
    if len(data) > max_bytes:
        raise WorkspaceError("file_too_large")
    target = resolve_inside(ws.path, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)  # rename atomic
    return target
