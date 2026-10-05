"""Generate a private local credential set, once. Does not contact any service."""

import os
import secrets
from pathlib import Path


def create_secrets(root: Path) -> None:
    directory = root / ".secrets"
    # Refuse existing folders, including symlinks, to prevent accidental credential rotation.
    directory.mkdir(mode=0o700, exist_ok=False)
    os.chmod(directory, 0o700)
    app = secrets.token_urlsafe(32)
    migrator = secrets.token_urlsafe(32)
    values = {
        "postgres_password": secrets.token_urlsafe(32),
        "app_password": app,
        "migrator_password": migrator,
        "database_url": f"postgresql+psycopg://jarvis_app:{app}@postgres:5432/jarvis",
        "migration_database_url": (
            f"postgresql+psycopg://jarvis_migrator:{migrator}@postgres:5432/jarvis"
        ),
        "token_pepper": secrets.token_urlsafe(32),
    }
    for name, value in values.items():
        path = directory / name
        # Binary output avoids Windows translating LF into CRLF. PostgreSQL's
        # shell readers and Python must agree on the exact credential bytes.
        with path.open("xb") as file:
            file.write(value.encode("ascii") + b"\n")
        # Compose bind-mounted file secrets retain host permissions. The 0700 parent
        # protects host access, while 0444 lets UID 10001 read a single mounted file.
        os.chmod(path, 0o444)


if __name__ == "__main__":
    try:
        create_secrets(Path(__file__).resolve().parents[1])
    except FileExistsError:
        raise SystemExit(".secrets already exists. Refusing to overwrite credentials.") from None
    print("Private credential files created. No secret values were printed.")
