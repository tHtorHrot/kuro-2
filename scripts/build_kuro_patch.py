"""Package only session delta; historical manifests remain untouched, manifest excludes itself."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from ops_common import sha256, source_fingerprint

EXCLUDE = {
    ".git",
    ".venv",
    ".secrets",
    ".env",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "backups",
    "node_modules",
    ".coverage",
    "dist",
}


def build(root, baseline_zip, output, previous_candidate=None):
    with zipfile.ZipFile(baseline_zip) as original:
        baseline = {
            row.filename: original.read(row) for row in original.infolist() if not row.is_dir()
        }
    previous_files = {}
    previous = None
    if previous_candidate is not None:
        with zipfile.ZipFile(previous_candidate) as archive:
            previous_manifest_bytes = archive.read("KURO_PATCH_MANIFEST.json")
            previous_manifest = json.loads(previous_manifest_bytes)
            if previous_manifest["baseline_zip_sha256"] != sha256(baseline_zip):
                raise ValueError("Previous candidate uses a different baseline")
            for row in previous_manifest["files"]:
                if hashlib.sha256(archive.read(row["path"])).hexdigest() != row["sha256"]:
                    raise ValueError("Previous candidate payload integrity mismatch")
                previous_files[row["path"]] = row["sha256"]
        previous = {
            "archive_sha256": sha256(previous_candidate),
            "source_hash": previous_manifest["source"]["hash"],
            "manifest_sha256": hashlib.sha256(previous_manifest_bytes).hexdigest(),
        }
    files = []
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts
        if not path.is_file() or any(part in EXCLUDE for part in parts) or parts[0] == "operations":
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "KURO_PATCH_MANIFEST.json" or path.suffix == ".pyc":
            continue
        data = path.read_bytes()
        if baseline.get(relative) == data:
            continue
        old = baseline.get(relative)
        files.append(
            {
                "path": relative,
                "operation": "replace" if old is not None else "add",
                "sha256": sha256(path),
                "size": len(data),
                "baseline_sha256": hashlib.sha256(old).hexdigest() if old is not None else None,
                "previous_candidate_sha256": previous_files.get(relative),
                "baseline_lf_sha256": hashlib.sha256(old.replace(b"\r\n", b"\n")).hexdigest()
                if old is not None
                else None,
            }
        )
    missing = [name for name in baseline if not (root / name).is_file()]
    if missing:
        raise ValueError("Unexpected deletions; include an explicit reviewed deletion list")
    manifest = {
        "format": "kuro-cumulative-patch-v1",
        "baseline_zip_sha256": sha256(baseline_zip),
        "schema_from": "0008_executor_binding",
        "schema_to": "0009_calendar_tasks",
        "source": source_fingerprint(root),
        "previous_candidate": previous,
        "files": files,
        "deleted_files": [],
        "self_exclusion": "KURO_PATCH_MANIFEST.json is included but not hashed in itself",
    }
    (root / "KURO_PATCH_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row in files:
            archive.write(root / row["path"], row["path"])
        archive.write(root / "KURO_PATCH_MANIFEST.json", "KURO_PATCH_MANIFEST.json")
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for row in files:
            assert hashlib.sha256(archive.read(row["path"])).hexdigest() == row["sha256"]
    return {
        "archive": output.name,
        "sha256": sha256(output),
        "files": len(files),
        "deletions": missing,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--previous-candidate", type=Path)
    args = p.parse_args()
    print(
        json.dumps(
            build(
                Path(__file__).resolve().parents[1],
                args.baseline,
                args.output,
                args.previous_candidate,
            )
        )
    )
