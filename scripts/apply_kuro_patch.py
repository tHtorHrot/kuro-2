"""Review/apply byte-verified cumulative patch; refuse user changes and private paths."""

import argparse
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from ops_common import OpsError, private_folder, sha256

FORBIDDEN = {".secrets", ".env", ".git", ".venv", "backups", "node_modules"}


def safe_relative(name):
    p = PurePosixPath(name)
    if (
        not p.parts
        or p.is_absolute()
        or ".." in p.parts
        or "\\" in name
        or p.parts[0] in FORBIDDEN
        or any(":" in part for part in p.parts)
    ):
        raise OpsError("Forbidden patch path")
    return p


def preflight(patch, target, manifest, *, allow_newlines=False):
    import hashlib

    checks = []
    for row in manifest["files"]:
        relative = safe_relative(row["path"])
        source, destination = patch / str(relative), target / str(relative)
        if destination.exists() and not destination.is_file():
            raise OpsError("Target path conflicts with a directory: " + row["path"])
        if not source.is_file() or source.is_symlink() or sha256(source) != row["sha256"]:
            raise OpsError("Patch payload integrity mismatch: " + row["path"])
        for part in [destination, *destination.parents]:
            if part == target.parent:
                break
            if part.is_symlink():
                raise OpsError("Target patch path cannot be a symlink")
        current = sha256(destination) if destination.is_file() else None
        if current == row["sha256"]:
            checks.append((row, "already_current"))
        elif current == row.get("baseline_sha256"):
            checks.append((row, "byte_baseline"))
        elif current is not None and current == row.get("previous_candidate_sha256"):
            checks.append((row, "byte_previous_candidate"))
        elif (
            allow_newlines
            and destination.is_file()
            and row.get("baseline_lf_sha256")
            and hashlib.sha256(destination.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            == row["baseline_lf_sha256"]
        ):
            checks.append((row, "newline_only_baseline; byte_hash_different"))
        else:
            raise OpsError("User change/baseline conflict: " + row["path"])
    # The manifest excludes its own hash in the package. Validate/copy its actual
    # bytes separately so an updated installation retains the new release map.
    metadata = patch / "KURO_PATCH_MANIFEST.json"
    if metadata.exists():
        if metadata.is_symlink() or not metadata.is_file():
            raise OpsError("Invalid patch manifest path")
        if json.loads(metadata.read_text()) != manifest:
            raise OpsError("Patch manifest differs from the validated release map")
        destination = target / metadata.name
        for part in [destination, *destination.parents]:
            if part == target.parent:
                break
            if part.is_symlink():
                raise OpsError("Target patch path cannot be a symlink")
        if destination.exists() and not destination.is_file():
            raise OpsError("Target manifest path conflicts with a directory")
        current = sha256(destination) if destination.is_file() else None
        final = sha256(metadata)
        previous = (manifest.get("previous_candidate") or {}).get("manifest_sha256")
        if current == final:
            match = "already_current"
        elif current is None:
            match = "byte_baseline"
        elif previous is not None and current == previous:
            match = "byte_previous_candidate"
        else:
            raise OpsError("User change/baseline conflict: " + metadata.name)
        checks.append(({"path": metadata.name, "sha256": final}, match))
    return checks


def apply(patch, target, manifest, *, allow_newlines=False):
    checks = preflight(patch, target, manifest, allow_newlines=allow_newlines)
    changes = [row for row, match in checks if match != "already_current"]
    if not changes:
        return None
    backup = private_folder(
        target / "backups" / ("patch-files-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
    )
    journal = []
    try:
        for row in changes:
            relative = safe_relative(row["path"])
            destination = target / str(relative)
            saved = backup / str(relative)
            exists = destination.is_file()
            if exists:
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            destination.parent.mkdir(parents=True, exist_ok=True)
            journal.append((destination, saved if exists else None))
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
                temp_path = Path(temporary.name)
                with (patch / str(relative)).open("rb") as source:
                    shutil.copyfileobj(source, temporary)
            temp_path.replace(destination)
        (backup / "applied.json").write_text(
            json.dumps([row["path"] for row in changes], indent=2) + "\n"
        )
    except (OSError, OpsError):
        for destination, saved in reversed(journal):
            if saved:
                shutil.copy2(saved, destination)
            else:
                destination.unlink(missing_ok=True)
        raise OpsError(
            "Patch application failed; source files restored from local backup"
        ) from None
    return backup


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", type=Path, default=Path(r"A:\Kuro2\kuro-main"))
    p.add_argument("--patch-dir", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--allow-newline-only", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    manifest = json.loads((args.patch_dir / "KURO_PATCH_MANIFEST.json").read_text())
    if not args.target.is_dir() or not (args.target / "src/jarvis").is_dir():
        raise SystemExit("Target project root not found; no changes made")
    try:
        checked = preflight(
            args.patch_dir, args.target, manifest, allow_newlines=args.allow_newline_only
        )
        print(
            json.dumps(
                {
                    "files": len(checked),
                    "checks": [{"path": row["path"], "match": match} for row, match in checked],
                }
            )
        )
        if args.apply:
            saved = apply(
                args.patch_dir, args.target, manifest, allow_newlines=args.allow_newline_only
            )
            print(
                json.dumps(
                    {
                        "applied": True,
                        "source_backup": str(saved) if saved else None,
                        "database_changed": False,
                        "private_files_changed": False,
                    }
                )
            )
    except (OpsError, OSError) as exc:
        raise SystemExit(
            f"Patch blocked: {type(exc).__name__}: {exc}; preserve files and stop"
        ) from None
