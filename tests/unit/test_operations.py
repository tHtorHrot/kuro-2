"""Host operations unit tests + actual isolated OpenSSL CMS encryption/archive recovery."""

import io
import json
import shutil
import subprocess
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def host_scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))


def test_cold_volume_roundtrip_and_empty_target_guard(tmp_path):
    from volume_archive import pack, unpack

    source = {name: tmp_path / "source" / name for name in ("documents", "qdrant", "models")}
    target = {name: tmp_path / "target" / name for name in source}
    for name, root in source.items():
        root.mkdir(parents=True)
        (root / "content.bin").write_bytes(name.encode() + b"\x00\xff")
    data = io.BytesIO()
    pack(source, data)
    data.seek(0)
    unpack(target, data)
    for name in source:
        assert (source[name] / "content.bin").read_bytes() == (
            target[name] / "content.bin"
        ).read_bytes()
    data.seek(0)
    with pytest.raises(ValueError, match="not empty"):
        unpack(target, data)


@pytest.mark.parametrize(
    "name,kind,link",
    [
        ("../escape", "file", ""),
        ("documents/../../escape", "file", ""),
        ("documents/link", "symlink", "/tmp/escape"),
        ("documents/device", "device", ""),
    ],
)
def test_restore_rejects_unsafe_archive_members(tmp_path, name, kind, link):
    from volume_archive import unpack

    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        row = tarfile.TarInfo(name)
        if kind == "symlink":
            row.type, row.linkname = tarfile.SYMTYPE, link
        if kind == "device":
            row.type = tarfile.CHRTYPE
        archive.addfile(row)
    data.seek(0)
    roots = {name: tmp_path / name for name in ("documents", "qdrant", "models")}
    with pytest.raises((ValueError, tarfile.TarError)):
        unpack(roots, data)
    assert not (tmp_path.parent / "escape").exists()


def test_bundle_integrity_detects_modified_bytes(tmp_path):
    from ops_backup import create_bundle, verify_bundle
    from ops_common import OpsError

    stage = tmp_path / "parts"
    stage.mkdir()
    for name, data in [
        ("database.dump", b"PGDMP\x00fixture"),
        ("volumes.tar", b"volumes"),
        ("config.tar", b"config"),
    ]:
        (stage / name).write_bytes(data)
    create_bundle(stage, tmp_path / "bundle.tar", {"format": "kuro-cold-backup-v1"})
    assert (
        verify_bundle(tmp_path / "bundle.tar", tmp_path / "ok")["format"] == "kuro-cold-backup-v1"
    )
    # Rewrite one archived member while retaining the original manifest.
    with (
        tarfile.open(tmp_path / "bundle.tar") as original,
        tarfile.open(tmp_path / "bad.tar", "w") as bad,
    ):
        for member in original:
            data = original.extractfile(member).read()
            if member.name == "volumes.tar":
                data += b"tampered"
                member.size = len(data)
            bad.addfile(member, io.BytesIO(data))
    with pytest.raises(OpsError, match="integrity mismatch"):
        verify_bundle(tmp_path / "bad.tar", tmp_path / "bad")


def test_real_cms_encrypted_backup_can_be_decrypted_verified_and_rejects_tampering(tmp_path):
    from ops_backup import cms_file, create_bundle, verify_bundle
    from ops_common import OpsError, sha256

    if not shutil.which("openssl"):
        import os

        if os.environ.get("JARVIS_REQUIRE_INTEGRATION") == "1":
            pytest.fail("OpenSSL required by the release Docker test image")
        pytest.skip("OpenSSL required for local encryption drill")
    key, cert = tmp_path / "ephemeral-key.pem", tmp_path / "public-cert.pem"
    generated = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=Ephemeral KURO Test",
            "-days",
            "1",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if generated.returncode != 0:
        import os

        # Windows host OpenSSL often lacks openssl.cnf; Docker Linux gate
        # must pass, local Windows may skip.
        if os.environ.get("JARVIS_REQUIRE_INTEGRATION") == "1" and os.name != "nt":
            pytest.fail(f"OpenSSL failed: {generated.stderr.decode(errors='replace')[:500]}")
        pytest.skip(f"OpenSSL unavailable: {generated.stderr.decode(errors='replace')[:200]}")
    assert generated.returncode == 0
    stage = tmp_path / "parts"
    stage.mkdir()
    for name, data in [
        ("database.dump", b"PGDMPfixture-private"),
        ("volumes.tar", b"originals"),
        ("config.tar", b"non-secret"),
    ]:
        (stage / name).write_bytes(data)
    create_bundle(stage, tmp_path / "bundle.tar", {"format": "kuro-cold-backup-v1"})
    encrypted, restored = tmp_path / "backup.cms", tmp_path / "decrypted.tar"
    params = {"certificate": cert, "certificate_sha256": sha256(cert)}
    cms_file(tmp_path / "bundle.tar", encrypted, **params)
    assert b"fixture-private" not in encrypted.read_bytes()
    cms_file(encrypted, restored, private_key=key, **params)
    manifest = verify_bundle(restored, tmp_path / "recovered")
    assert (tmp_path / "recovered" / "database.dump").read_bytes() == b"PGDMPfixture-private"
    assert not any("key" in name for name in manifest["files"])
    tampered = tmp_path / "tampered.cms"
    raw = bytearray(encrypted.read_bytes())
    raw[len(raw) // 2] ^= 1
    tampered.write_bytes(raw)
    with pytest.raises(OpsError):
        cms_file(tampered, tmp_path / "rejected.tar", private_key=key, **params)
    assert not (tmp_path / "rejected.tar").exists()


def test_backup_failure_still_resumes_the_original_paused_services(tmp_path, monkeypatch):
    from ops_backup import capture
    from ops_common import OpsError

    class FakeCompose:
        def __init__(self):
            self.calls = []

        def ps(self):
            return [
                {"ID": s, "Service": s, "State": "running"}
                for s in ("postgres", "scheduler", "qdrant")
            ]

        def image_identity(self, container_id):
            return {"image_id": "sha256:fixture", "repo_digests": []}

        def run(self, *args, **kwargs):
            self.calls.append(args)
            if args[0] == "images":
                return b'[{"ID":"sha256:fixture"}]'
            if "pg_dump" in args:
                raise OpsError("simulated disk full")
            return b""

        def sql(self, statement, **kwargs):
            return "0" if "pg_stat_activity" in statement else "0009_calendar_tasks"

    compose = FakeCompose()
    with pytest.raises(OpsError, match="disk full"):
        capture(compose, tmp_path, Path.cwd())
    assert compose.calls[-1] == ("start", "qdrant", "scheduler")
    assert not any("--volumes" in call for call in compose.calls)


@pytest.mark.parametrize("project", ["personal-jarvis", "jarvis", "../escape", "kuro-restore-"])
def test_restore_refuses_production_or_invalid_project(project):
    from ops_common import OpsError
    from ops_restore import validate_project

    with pytest.raises(OpsError):
        validate_project(project)


def test_restore_configuration_has_no_executor_transport_or_secrets():
    from ops_restore import validate_restore_config

    validate_restore_config(Path.cwd())


def test_monitor_future_job_is_not_stale_and_alarm_recovery_is_deduplicated():
    from ops_watch import alarm_codes, transitions

    health = {
        "database_ready": True,
        "actions": {"queued": 1},
        "due_age_seconds": None,
        "heartbeat": {"scheduler": {"expected": True, "recent": True}},
    }
    assert not alarm_codes(health, backup_age=0, disk_free=10 * 1024**3)
    health["heartbeat"]["scheduler"]["recent"] = False
    current = alarm_codes(health, backup_age=0, disk_free=10 * 1024**3)
    now = datetime.now(UTC).isoformat()
    assert transitions(set(), current, now) == [
        {"code": "worker_stale:scheduler", "state": "alarm", "at_utc": now}
    ]
    assert transitions(current, current, now) == []
    assert transitions(current, set(), now)[0]["state"] == "recovered"


def test_monitor_signal_derives_ok_no_signal_idle_without_persisting():
    from jarvis.operations.monitor import derive_signal

    assert derive_signal(True, 10) == "ok"
    assert derive_signal(True, 90) == "ok"
    assert derive_signal(True, 90.1) == "no_signal"
    assert derive_signal(True, None) == "no_signal"
    assert derive_signal(False, 10) == "idle"
    assert derive_signal(False, None) == "idle"


def test_rollback_guard_rejects_old_image_new_schema():
    from rollback_guard import compatible

    record = {"image_digest": "sha256:old", "supported_schema_heads": ["0008_executor_binding"]}
    assert not compatible("0009_calendar_tasks", "sha256:old", record)
    assert compatible("0008_executor_binding", "sha256:old", record)


def test_patch_preflight_rejects_user_edits_and_allows_idempotent_apply(tmp_path):
    from apply_kuro_patch import apply, preflight
    from ops_common import OpsError, sha256

    patch, target = tmp_path / "patch", tmp_path / "target"
    patch.mkdir()
    target.mkdir()
    (patch / "example.py").write_text("new\n")
    (target / "example.py").write_text("old\n")
    manifest = {
        "files": [
            {
                "path": "example.py",
                "sha256": sha256(patch / "example.py"),
                "baseline_sha256": sha256(target / "example.py"),
            }
        ]
    }
    preflight(patch, target, manifest)
    backup = apply(patch, target, manifest)
    assert (backup / "example.py").read_text() == "old\n"
    assert apply(patch, target, manifest) is None
    (target / "example.py").write_text("user edit\n")
    with pytest.raises(OpsError, match="User change"):
        apply(patch, target, manifest)
    assert (target / "example.py").read_text() == "user edit\n"


def test_patch_update_accepts_known_candidate_bytes_and_preserves_user_changes(tmp_path):
    from apply_kuro_patch import apply, preflight
    from ops_common import OpsError, sha256

    patch, target = tmp_path / "patch", tmp_path / "target"
    patch.mkdir()
    target.mkdir()
    (patch / "example.py").write_text("fixed candidate\n")
    (target / "example.py").write_text("previous candidate\n")
    manifest = {
        "files": [
            {
                "path": "example.py",
                "sha256": sha256(patch / "example.py"),
                "baseline_sha256": None,
                "previous_candidate_sha256": sha256(target / "example.py"),
            }
        ]
    }
    assert preflight(patch, target, manifest)[0][1] == "byte_previous_candidate"
    (target / "example.py").write_text("user correction\n")
    with pytest.raises(OpsError, match="User change"):
        apply(patch, target, manifest)
    assert (target / "example.py").read_text() == "user correction\n"
    (target / "example.py").write_text("previous candidate\n")
    backup = apply(patch, target, manifest)
    assert (backup / "example.py").read_text() == "previous candidate\n"
    assert (target / "example.py").read_text() == "fixed candidate\n"
    assert apply(patch, target, manifest) is None


def test_patch_updates_manifest_without_self_hash_and_rejects_unknown_metadata(tmp_path):
    from apply_kuro_patch import apply
    from ops_common import OpsError, sha256

    patch, target = tmp_path / "patch", tmp_path / "target"
    patch.mkdir()
    target.mkdir()
    old = target / "KURO_PATCH_MANIFEST.json"
    old.write_text('{"old_candidate": true}\n')
    old_bytes = old.read_bytes()
    manifest = {"files": [], "previous_candidate": {"manifest_sha256": sha256(old)}}
    (patch / old.name).write_text(json.dumps(manifest) + "\n")
    old.write_text('{"user_note": true}\n')
    with pytest.raises(OpsError, match="User change"):
        apply(patch, target, manifest)
    assert json.loads(old.read_text()) == {"user_note": True}
    old.write_bytes(old_bytes)
    backup = apply(patch, target, manifest)
    assert (backup / old.name).read_bytes() == old_bytes
    assert json.loads(old.read_text()) == manifest
    assert apply(patch, target, manifest) is None


def test_package_includes_operations_source_and_excludes_root_private_archives(tmp_path):
    from build_kuro_patch import build

    root = tmp_path / "root"
    source = root / "src/jarvis/operations/monitor.py"
    source.parent.mkdir(parents=True)
    source.write_text("def monitor(): return 'ready'\n")
    archive = root / "operations/private-backup.tar"
    archive.parent.mkdir()
    archive.write_bytes(b"private data")
    secret = root / ".secrets/token"
    secret.parent.mkdir()
    secret.write_text("private-token")
    baseline, output = tmp_path / "baseline.zip", tmp_path / "patch.zip"
    with zipfile.ZipFile(baseline, "w"):
        pass
    build(root, baseline, output)
    with zipfile.ZipFile(output) as packaged:
        assert packaged.read("src/jarvis/operations/monitor.py") == source.read_bytes()
        assert "operations/private-backup.tar" not in packaged.namelist()
        assert ".secrets/token" not in packaged.namelist()


@pytest.mark.parametrize("exit_code,output", [(0, b""), (1, b"KURO_PRIVATE_DACL_OK\r\n")])
def test_windows_private_folder_requires_native_success_and_readback_attestation(
    tmp_path, monkeypatch, exit_code, output
):
    import ops_common

    def native(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], exit_code, stdout=output, stderr=b"")

    monkeypatch.setattr(ops_common.subprocess, "run", native)
    with pytest.raises(ops_common.OpsError, match="DACL verification failed"):
        ops_common.windows_private_dacl(tmp_path)


def test_windows_private_folder_accepts_attestation_and_passes_path_as_data(tmp_path, monkeypatch):
    import ops_common

    folder = tmp_path / "quote';not-code"

    def native(command, **kwargs):
        assert "quote';not-code" not in command[-1]
        assert kwargs["env"]["KURO_PRIVATE_DIR"] == str(folder.resolve())
        return subprocess.CompletedProcess(
            command, 0, stdout=b"KURO_PRIVATE_DACL_OK\r\n", stderr=b""
        )

    monkeypatch.setattr(ops_common.subprocess, "run", native)
    ops_common.windows_private_dacl(folder)
