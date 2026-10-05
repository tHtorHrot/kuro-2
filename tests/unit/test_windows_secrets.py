import importlib.util
import json
import os
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_uses_portable_newlines(monkeypatch, tmp_path):
    generator = load_script("setup_local")
    real_open = Path.open

    def windows_open(path, mode="r", *args, **kwargs):
        if "b" not in mode and any(flag in mode for flag in "wax"):
            kwargs["newline"] = "\r\n"
        return real_open(path, mode, *args, **kwargs)

    # Simulate Windows text newline translation even when tests run on Linux.
    monkeypatch.setattr(Path, "open", windows_open)
    generator.create_secrets(tmp_path)
    for path in (tmp_path / ".secrets").iterdir():
        data = path.read_bytes()
        assert data.endswith(b"\n") and b"\r" not in data
        assert len(data.splitlines()) == 1


@pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="Linux bootstrap shell check")
def test_bootstrap_reads_legacy_windows_files_without_extra_password_byte(tmp_path):
    secret_dir = tmp_path / "secret files"
    secret_dir.mkdir()
    (secret_dir / "app_password").write_bytes(b"synthetic-app\r\n")
    (secret_dir / "migrator_password").write_bytes(b"synthetic-migrator\r\n")
    commands = tmp_path / "bin"
    commands.mkdir()
    psql = commands / "psql"
    psql.write_text(
        "#!/bin/sh\nset -eu\n"
        '[ "$JARVIS_APP_PASSWORD" = "synthetic-app" ]\n'
        '[ "$JARVIS_MIGRATOR_PASSWORD" = "synthetic-migrator" ]\n'
        "cat >/dev/null\n",
        encoding="ascii",
        newline="\n",
    )
    psql.chmod(0o755)
    script = (
        (ROOT / "infra/postgres/bootstrap.sh")
        .read_text()
        .replace("/run/secrets", shlex.quote(str(secret_dir)))
    )
    result = subprocess.run(
        ["sh", "-s"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "POSTGRES_USER": "postgres",
            "POSTGRES_DB": "jarvis",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.fixture
def project(tmp_path):
    load_script("setup_local").create_secrets(tmp_path)
    (tmp_path / "compose.yaml").write_text("name: personal-jarvis\n")
    for path in (tmp_path / ".secrets").iterdir():
        mode = stat.S_IMODE(path.stat().st_mode)
        data = path.read_bytes().rstrip(b"\n") + b"\r\n"
        path.chmod(mode | stat.S_IWUSR)
        path.write_bytes(data)
        path.chmod(mode)
    return tmp_path


def snapshot(project):
    return {p.name: p.read_bytes() for p in (project / ".secrets").iterdir()}


def fake_probes(module, project, states, commands, *, wrong_mount=False):
    files = module.load_files(project)
    state_iter = iter(states)

    def run(root, script):
        commands.append(script)
        if script == module.REPAIR_SCRIPT:
            return b""
        status = next(state_iter)
        rows = []
        for role, name in module.ROLE_FILES.items():
            normal, legacy = status.get(role, ("ok", "ok"))
            fingerprint = module.hashlib.sha256(files[name]).hexdigest()
            if wrong_mount:
                fingerprint = "0" * 64
            rows.append(f"{role}|{normal}|{legacy}|{fingerprint}")
        return ("\n".join(rows) + "\n").encode("ascii")

    return run


def test_repair_preserves_secrets_data_and_file_permissions(monkeypatch, project):
    module = load_script("repair_windows_secrets")
    original = snapshot(project)
    commands = []
    broken = {role: ("fail", "ok") for role in module.ROLE_FILES}
    monkeypatch.setattr(
        module, "run_in_postgres", fake_probes(module, project, [broken, {}], commands)
    )
    result = module.repair(project)
    assert result["crlf_password_mismatch_confirmed"] is True
    assert result["secret_files_normalized"] == 6
    assert commands.count(module.REPAIR_SCRIPT) == 1
    for path in (project / ".secrets").iterdir():
        assert path.read_bytes() == original[path.name].replace(b"\r\n", b"\n")
        assert not path.stat().st_mode & stat.S_IWUSR
    for value in original.values():
        assert value.strip().decode() not in json.dumps(result)


def test_unrelated_auth_failure_makes_no_changes(monkeypatch, project):
    module = load_script("repair_windows_secrets")
    original = snapshot(project)
    commands = []
    monkeypatch.setattr(
        module,
        "run_in_postgres",
        fake_probes(module, project, [{"jarvis_migrator": ("fail", "fail")}], commands),
    )
    with pytest.raises(module.RepairError, match="cause not confirmed"):
        module.repair(project)
    assert snapshot(project) == original
    assert module.REPAIR_SCRIPT not in commands


def test_wrong_compose_secret_mount_makes_no_changes(monkeypatch, project):
    module = load_script("repair_windows_secrets")
    original = snapshot(project)
    commands = []
    monkeypatch.setattr(
        module, "run_in_postgres", fake_probes(module, project, [{}], commands, wrong_mount=True)
    )
    with pytest.raises(module.RepairError, match="Container secrets differ"):
        module.repair(project)
    assert snapshot(project) == original
    assert module.REPAIR_SCRIPT not in commands


def test_repair_is_repeatable_without_resetting_valid_passwords(monkeypatch, project):
    module = load_script("repair_windows_secrets")
    commands = []
    monkeypatch.setattr(
        module, "run_in_postgres", fake_probes(module, project, [{}, {}, {}, {}], commands)
    )
    first = module.repair(project)
    second = module.repair(project)
    assert first["secret_files_normalized"] == 6
    assert second["secret_files_normalized"] == 0
    assert not first["database_passwords_normalized"]
    assert module.REPAIR_SCRIPT not in commands


def test_repair_failure_leaves_host_files_intact(monkeypatch, project):
    module = load_script("repair_windows_secrets")
    original = snapshot(project)

    def run(root, script):
        if script == module.REPAIR_SCRIPT:
            raise module.RepairError("Simulated database transaction failure")
        return fake_probes(module, project, [{"jarvis_migrator": ("fail", "ok")}], [])(root, script)

    monkeypatch.setattr(module, "run_in_postgres", run)
    with pytest.raises(module.RepairError):
        module.repair(project)
    assert snapshot(project) == original


def test_custom_url_refused_before_docker(monkeypatch, project):
    module = load_script("repair_windows_secrets")
    path = project / ".secrets" / "database_url"
    path.chmod(0o600)
    path.write_bytes(path.read_bytes().replace(b"@postgres:", b"@other-server:"))
    monkeypatch.setattr(
        module, "run_in_postgres", lambda *_: pytest.fail("Must not contact Docker")
    )
    with pytest.raises(module.RepairError, match="App URL"):
        module.repair(project)


def test_docker_error_does_not_echo_sensitive_output(monkeypatch, project):
    module = load_script("repair_windows_secrets")
    secret = "this-output-must-not-be-visible"
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a, 1, stdout=secret.encode(), stderr=secret.encode()
        ),
    )
    with pytest.raises(module.RepairError) as error:
        module.run_in_postgres(project, module.PROBE_SCRIPT)
    assert secret not in str(error.value)
