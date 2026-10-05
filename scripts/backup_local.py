"""Create a private local pg_dump before upgrade; preserves binary bytes on PowerShell."""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def backup(root: Path) -> Path:
    folder = root / "backups"
    if folder.is_symlink():
        raise ValueError("Backup folder cannot be a symlink")
    folder.mkdir(mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    path = folder / (
        "jarvis-before-upgrade-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".dump"
    )
    try:
        with path.open("xb") as output:
            os.chmod(path, 0o600)
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(root / "compose.yaml"),
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "-U",
                    "postgres",
                    "-d",
                    "jarvis",
                    "--format=custom",
                    "--no-owner",
                ],
                cwd=root,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
            output.flush()
            os.fsync(output.fileno())
        with path.open("rb") as source:
            signature = source.read(5)
        if result.returncode != 0 or signature != b"PGDMP":
            raise ValueError("Local backup failed; no database changes were made")
        return path
    except (OSError, ValueError, subprocess.SubprocessError):
        path.unlink(missing_ok=True)
        raise ValueError("Local backup failed; check Docker/PostgreSQL availability") from None


if __name__ == "__main__":
    try:
        path = backup(Path(__file__).resolve().parents[1])
        print(
            json.dumps(
                {
                    "backup": str(path),
                    "encrypted": False,
                    "notice": "Keep private; this is a local upgrade backup, not offsite backup.",
                }
            )
        )
    except ValueError as error:
        raise SystemExit(str(error)) from None
