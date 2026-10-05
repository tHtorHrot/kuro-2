"""Repair v0.1.0 Windows CRLF credentials without regenerating secrets or deleting data.

Runs on the trusted operator's machine. Only the original Compose layout is supported.
All database authentication probes run inside the existing postgres container. Passwords
are read from its mounted files, never passed as process arguments or printed.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

SECRET_NAMES = (
    "postgres_password",
    "app_password",
    "migrator_password",
    "database_url",
    "migration_database_url",
    "token_pepper",
)
ROLE_FILES = {
    "postgres": "postgres_password",
    "jarvis_app": "app_password",
    "jarvis_migrator": "migrator_password",
}

PROBE_SCRIPT = r"""set -eu
probe() {
    role="$1"
    filename="$2"
    normal=fail
    legacy=fail
    canonical="$(tr -d '\r\n' < "$filename")"
    raw="$(cat "$filename")"
    if PGPASSWORD="$canonical" PGCONNECT_TIMEOUT=3 psql -X -h 127.0.0.1 \
        -p 5432 -U "$role" -d jarvis -v ON_ERROR_STOP=1 -Atqc 'SELECT 1' >/dev/null 2>&1; then
        normal=ok
    fi
    if PGPASSWORD="$raw" PGCONNECT_TIMEOUT=3 psql -X -h 127.0.0.1 \
        -p 5432 -U "$role" -d jarvis -v ON_ERROR_STOP=1 -Atqc 'SELECT 1' >/dev/null 2>&1; then
        legacy=ok
    fi
    fingerprint="$(printf '%s' "$canonical" | sha256sum)"
    fingerprint="${fingerprint%% *}"
    printf '%s|%s|%s|%s\n' "$role" "$normal" "$legacy" "$fingerprint"
}
probe postgres /run/secrets/postgres_password
probe jarvis_app /run/secrets/app_password
probe jarvis_migrator /run/secrets/migrator_password
"""

REPAIR_SCRIPT = r"""set -eu
export JARVIS_POSTGRES_PASSWORD="$(tr -d '\r\n' < /run/secrets/postgres_password)"
export JARVIS_APP_PASSWORD="$(tr -d '\r\n' < /run/secrets/app_password)"
export JARVIS_MIGRATOR_PASSWORD="$(tr -d '\r\n' < /run/secrets/migrator_password)"
psql -X -U postgres -d jarvis -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
\getenv postgres_password JARVIS_POSTGRES_PASSWORD
\getenv app_password JARVIS_APP_PASSWORD
\getenv migrator_password JARVIS_MIGRATOR_PASSWORD
BEGIN;
SET LOCAL log_statement = 'none';
SET LOCAL log_min_error_statement = 'panic';
SET LOCAL log_error_verbosity = 'terse';
SET LOCAL password_encryption = 'scram-sha-256';
ALTER ROLE postgres PASSWORD :'postgres_password';
ALTER ROLE jarvis_app PASSWORD :'app_password';
ALTER ROLE jarvis_migrator PASSWORD :'migrator_password';
COMMIT;
SQL
unset JARVIS_POSTGRES_PASSWORD JARVIS_APP_PASSWORD JARVIS_MIGRATOR_PASSWORD
"""


class RepairError(RuntimeError):
    """Messages contain only fixed diagnostic text or nonsecret filenames."""


def load_files(root: Path) -> dict[str, bytes]:
    folder = root / ".secrets"
    if folder.is_symlink() or not folder.is_dir():
        raise RepairError("Expected the original .secrets directory in the project.")
    files = {}
    for name in SECRET_NAMES:
        path = folder / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
            raise RepairError(f"Missing or unsupported secret file: {name}")
        data = path.read_bytes()
        if data.endswith(b"\r\n"):
            value = data[:-2]
        elif data.endswith(b"\n"):
            value = data[:-1]
        else:
            value = data
        if not value or b"\r" in value or b"\n" in value:
            raise RepairError(f"Unexpected file format: {name}")
        files[name] = value
    for name in (*ROLE_FILES.values(), "token_pepper"):
        if not re.fullmatch(rb"[A-Za-z0-9_-]{43}", files[name]):
            raise RepairError(
                "Only untouched URL-safe credentials from setup_local.py are supported."
            )
    expected_app = b"postgresql+psycopg://jarvis_app:" + files["app_password"]
    expected_migrator = b"postgresql+psycopg://jarvis_migrator:" + files["migrator_password"]
    suffix = b"@postgres:5432/jarvis"
    if files["database_url"] != expected_app + suffix:
        raise RepairError("App URL does not match the original Compose credential files.")
    if files["migration_database_url"] != expected_migrator + suffix:
        raise RepairError("Migrator URL does not match the original Compose credential files.")
    return files


def run_in_postgres(root: Path, script: str) -> bytes:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(root / "compose.yaml"),
            "exec",
            "-T",
            "postgres",
            "sh",
            "-s",
        ],
        cwd=root,
        input=script.encode("ascii"),
        capture_output=True,
        timeout=40,
        check=False,
    )
    if result.returncode:
        # Do not echo subprocess output: an unexpected failure could include sensitive details.
        raise RepairError(
            "Database check/repair failed. No volume was deleted. Inspect service logs."
        )
    return result.stdout


def probe(root: Path, files: dict[str, bytes]) -> dict[str, tuple[str, str]]:
    output = run_in_postgres(root, PROBE_SCRIPT)
    result = {}
    for row in output.decode("ascii").splitlines():
        columns = row.split("|")
        if len(columns) != 4:
            raise RepairError("Unexpected authentication check output; stopping.")
        role, normal, legacy, fingerprint = columns
        if role not in ROLE_FILES or normal not in {"ok", "fail"} or legacy not in {"ok", "fail"}:
            raise RepairError("Unexpected authentication check output; stopping.")
        expected = hashlib.sha256(files[ROLE_FILES[role]]).hexdigest()
        if fingerprint != expected or role in result:
            raise RepairError("Container secrets differ from this project; no repair attempted.")
        result[role] = normal, legacy
    if set(result) != set(ROLE_FILES):
        raise RepairError("Incomplete authentication check; no repair attempted.")
    return result


def normalize_files(root: Path, files: dict[str, bytes]) -> int:
    changed = 0
    for name, canonical in files.items():
        path = root / ".secrets" / name
        target = canonical + b"\n"
        if path.read_bytes() == target:
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        # Modify in place so existing bind mounts continue to refer to the same file.
        os.chmod(path, mode | stat.S_IWUSR)
        try:
            with path.open("wb") as file:
                file.write(target)
                file.flush()
                os.fsync(file.fileno())
        finally:
            os.chmod(path, mode)
        changed += 1
    return changed


def repair(root: Path) -> dict:
    if not (root / "compose.yaml").is_file():
        raise RepairError("Run this from the Jarvis project containing compose.yaml.")
    files = load_files(root)
    before = probe(root, files)
    if any(normal == legacy == "fail" for normal, legacy in before.values()):
        raise RepairError(
            "CRLF cause not confirmed: a role rejects both formats. "
            "No files/passwords changed. Inspect postgres and migrate logs."
        )
    requires_repair = any(normal == "fail" and legacy == "ok" for normal, legacy in before.values())
    if requires_repair:
        run_in_postgres(root, REPAIR_SCRIPT)
    after = probe(root, files)
    if any(normal != "ok" for normal, _ in after.values()):
        raise RepairError(
            "Canonical authentication did not pass. Keep the volume and secret files."
        )
    normalized_count = normalize_files(root, files)
    return {
        "status": "credentials_verified",
        "crlf_password_mismatch_confirmed": requires_repair,
        "database_passwords_normalized": requires_repair,
        "secret_files_normalized": normalized_count,
        "existing_secret_values_preserved": True,
        "database_data_preserved": True,
        "next": "Rerun migrate, then start api and run doctor.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(repair(args.project.resolve()), ensure_ascii=False))
    except RepairError as exc:
        print(json.dumps({"status": "stopped", "reason": str(exc)}, ensure_ascii=False))
        raise SystemExit(2) from None
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "reason": (
                        "File or Docker operation failed/timed out. "
                        "Keep existing secrets and volume."
                    ),
                }
            )
        )
        raise SystemExit(3) from None


if __name__ == "__main__":
    main()
