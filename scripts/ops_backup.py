"""Cold consistent encrypted backup; legacy backup_local.py remains unchanged."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from ops_common import Compose, OpsError, private_folder, sha256, source_fingerprint

WRITERS = {
    "api",
    "telegram",
    "assistant",
    "knowledge",
    "scheduler",
    "task-worker",
    "automation-ticker",
}
READERS = {"postgres", "qdrant", "document-parser"}


def cms_file(
    source, target, *, certificate, certificate_sha256, private_key=None, passphrase_file=None
):
    """OpenSSL CMS AuthEnvelopedData: AES-256-GCM and RSA-OAEP-SHA256; no custom crypto."""
    if target.exists() or target.is_symlink():
        raise OpsError("Encryption output already exists")
    if (
        not re.fullmatch(r"[0-9a-fA-F]{64}", certificate_sha256)
        or sha256(certificate) != certificate_sha256.lower()
    ):
        raise OpsError("Recovery certificate pin mismatch")
    command = ["openssl", "cms", "-binary", "-in", str(source), "-out", str(target)]
    if private_key is not None:
        command += [
            "-decrypt",
            "-inform",
            "DER",
            "-recip",
            str(certificate),
            "-inkey",
            str(private_key),
        ]
        if passphrase_file:
            command += ["-passin", "file:" + str(passphrase_file)]
    else:
        command += [
            "-encrypt",
            "-stream",
            "-outform",
            "DER",
            "-aes-256-gcm",
            "-recip",
            str(certificate),
            "-keyopt",
            "rsa_padding_mode:oaep",
            "-keyopt",
            "rsa_oaep_md:sha256",
        ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900, check=False
        )
        if result.returncode or not target.is_file() or target.stat().st_size == 0:
            raise OpsError("OpenSSL CMS operation failed; check private recovery key/certificate")
        target.chmod(0o600)
    except (OSError, subprocess.SubprocessError, OpsError):
        target.unlink(missing_ok=True)
        raise OpsError("OpenSSL CMS operation failed; no plaintext deliverable retained") from None


def create_bundle(folder, output, manifest):
    files = {p.name: sha256(p) for p in folder.iterdir() if p.is_file()}
    manifest = {**manifest, "files": files}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with tarfile.open(output, "w") as archive:
        for path in sorted(folder.iterdir()):
            if path.is_file():
                archive.add(path, arcname=path.name)
    output.chmod(0o600)
    return manifest


def verify_bundle(bundle, destination):
    destination = private_folder(destination)
    if any(destination.iterdir()):
        raise OpsError("Bundle extraction target must be empty")
    seen = set()
    with tarfile.open(bundle, "r") as archive:
        for member in archive:
            if (
                not member.isfile()
                or "/" in member.name
                or "\\" in member.name
                or member.name in seen
            ):
                raise OpsError("Unsafe or duplicate bundle member")
            seen.add(member.name)
            archive.extract(member, destination, filter="data")
    manifest = json.loads((destination / "manifest.json").read_text())
    if manifest.get("format") != "kuro-cold-backup-v1":
        raise OpsError("Unknown backup format")
    if set(manifest["files"]) != seen - {"manifest.json"}:
        raise OpsError("Backup inventory mismatch")
    for name, expected in manifest["files"].items():
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(destination / name) != expected:
            raise OpsError("Backup integrity mismatch")
    if not {"database.dump", "volumes.tar", "config.tar"}.issubset(seen):
        raise OpsError("Incomplete backup")
    with (destination / "database.dump").open("rb") as source:
        if source.read(5) != b"PGDMP":
            raise OpsError("Invalid database dump")
    return manifest


def capture(compose, stage, root, *, max_pause=600):
    running = [row for row in compose.ps() if row.get("State") == "running"]
    services = {row["Service"] for row in running}
    if "postgres" not in services or services - WRITERS - READERS:
        raise OpsError(
            "Expected PostgreSQL with only known writers/readers; stop operator jobs first"
        )
    if not {"knowledge", "qdrant"}.intersection(services):
        raise OpsError("Complete backup requires the existing knowledge volumes/services")
    paused = sorted(services & (WRITERS | {"qdrant"}))
    images = {}
    for row in running:
        images[row["Service"]] = compose.image_identity(row["ID"])
    started = time.monotonic()
    boundary = datetime.now(UTC).isoformat()
    stop_attempted = False

    def remaining():
        value = int(max_pause - (time.monotonic() - started))
        if value <= 0:
            raise OpsError("Maximum backup pause exceeded")
        return value

    try:
        stop_attempted = True
        compose.run("stop", "--timeout", "240", *paused, timeout=remaining())
        clients = int(
            compose.sql(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND usename IN ('jarvis_app','jarvis_migrator') AND pid<>pg_backend_pid()"
            )
        )
        if clients:
            raise OpsError("App/operator DB sessions remain; consistency boundary not established")
        schema = compose.sql("SELECT version_num FROM public.jarvis_schema_version")
        with (stage / "database.dump").open("xb") as output:
            compose.run(
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
                output=output,
                timeout=remaining(),
            )
        with (stage / "database.dump").open("rb") as source:
            if source.read(5) != b"PGDMP":
                raise OpsError("Database dump invalid")
        with (stage / "volumes.tar").open("xb") as output:
            compose.run(
                "run", "--rm", "--no-deps", "-T", "backup-files", output=output, timeout=remaining()
            )
        with tarfile.open(stage / "config.tar", "w") as archive:
            for path in sorted(root.glob("compose*.yaml")):
                archive.add(path, arcname=path.name)
            for name in ("Dockerfile", "pyproject.toml", "uv.lock", "alembic.ini"):
                archive.add(root / name, arcname=name)
        return {
            "format": "kuro-cold-backup-v1",
            "schema": schema,
            "consistency_boundary_utc": boundary,
            "writers_paused": paused,
            "capture_seconds": round(time.monotonic() - started, 3),
            "images_observed": images,
            "source": source_fingerprint(root),
            "source_mapping": "Host checkout fingerprint; observed image IDs recorded separately. "
            "No unverified build/source mapping is asserted.",
            "index_strategy": "cold Qdrant volume; restore with recorded identical image",
            "embedding_strategy": "entire embedding-models volume, byte checksummed in volumes.tar",
            "secret_recovery": "Separate private copy of original .secrets/.env required; "
            "preserve DB passwords, HMAC pepper and provider credentials. "
            "No credentials or decryption keys in this archive.",
            "offsite": "not_activated",
            "rpo_seconds": None,
        }
    finally:
        if stop_attempted:
            try:
                # Same full overlay chain and original containers; never recreate credential mounts.
                compose.run("start", *paused, timeout=120)
            except OpsError:
                raise OpsError(
                    "Backup pause recovery failed; manually start the listed writers"
                ) from None


def run_backup(
    root, compose, output_dir, certificate, certificate_sha256, *, max_pause=600, offsite_dir=None
):
    if not shutil.which("openssl") or not shutil.which("docker"):
        raise OpsError("OpenSSL and Docker required before any writer is paused")
    folder = private_folder(output_dir)
    prefix = "kuro-complete-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    encrypted = folder / (prefix + ".tar.cms")
    with tempfile.TemporaryDirectory(prefix="kuro-private-", dir=folder) as temporary:
        temp = private_folder(temporary)
        probe = temp / "probe.bin"
        probe.write_bytes(b"KURO recovery certificate preflight")
        cms_file(
            probe,
            temp / "probe.cms",
            certificate=certificate,
            certificate_sha256=certificate_sha256,
        )
        probe.unlink()
        (temp / "probe.cms").unlink()
        stage = private_folder(temp / "parts")
        manifest = capture(compose, stage, root, max_pause=max_pause)
        bundle = temp / "bundle.tar"
        create_bundle(stage, bundle, manifest)
        cms_file(bundle, encrypted, certificate=certificate, certificate_sha256=certificate_sha256)
    checksum = sha256(encrypted)
    (folder / (encrypted.name + ".sha256")).write_text(checksum + "  " + encrypted.name + "\n")
    offsite = "not_activated"
    if offsite_dir:
        target_dir = private_folder(offsite_dir)
        if target_dir.resolve() == folder.resolve():
            raise OpsError("Offsite destination must differ from local backup folder")
        target = target_dir / encrypted.name
        with encrypted.open("rb") as source, target.open("xb") as output:
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        if sha256(target) != checksum:
            raise OpsError("Offsite copy integrity mismatch")
        offsite = "copied_to_operator_mount; geographic separation unverified"
    report = {
        "backup": encrypted.name,
        "sha256": checksum,
        "encrypted": True,
        "completed_utc": datetime.now(UTC).isoformat(),
        "schema": manifest["schema"],
        "capture_seconds": manifest["capture_seconds"],
        "offsite": offsite,
        "restore_drill": "not_run",
        "rpo_seconds": None,
    }
    (folder / (prefix + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default="personal-jarvis")
    p.add_argument("--compose", action="append", required=True)
    p.add_argument("--recipient-cert", type=Path, required=True)
    p.add_argument("--cert-sha256", required=True, help="Pinned public recovery certificate SHA256")
    p.add_argument("--output-dir", default="backups/encrypted")
    p.add_argument("--offsite-dir", help="Operator-provisioned off-host mounted directory")
    p.add_argument("--max-pause-seconds", type=int, default=600)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not 30 <= args.max_pause_seconds <= 1800:
        raise OpsError("Maximum pause must be 30..1800 seconds")
    print(
        json.dumps(
            run_backup(
                root,
                Compose(root, args.project, args.compose),
                root / args.output_dir,
                args.recipient_cert,
                args.cert_sha256,
                max_pause=args.max_pause_seconds,
                offsite_dir=args.offsite_dir,
            )
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OpsError, OSError, ValueError, tarfile.TarError):
        raise SystemExit(
            "Backup failed; no credentials printed. Check local services/recovery certificate."
        ) from None
