import importlib.util
import json
import os
import subprocess
import warnings
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from jarvis.core.config import ConfigurationError
from jarvis.interfaces.telegram.config import load_bot_token, load_telegram_config

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "123456:" + "synthetic-test-token-only-000000000"


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_telegram_generator_uses_portable_newlines_and_never_overwrites(tmp_path):
    setup = script("setup_telegram")
    folder = tmp_path / ".secrets"
    folder.mkdir()
    setup.write_config(folder, UUID(int=1), 999, 123456, TOKEN)
    original = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert original["telegram_bot_token"] == TOKEN.encode() + b"\n"
    assert b"\r" not in original["telegram_config.json"]
    with pytest.raises(setup.SetupError, match="overwrite"):
        setup.private_folder(tmp_path)
    with pytest.raises(setup.SetupError):
        setup.write_config(folder, UUID(int=2), 111, 123456, "new-token")
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == original
    # Windows read-only files need writable flags for pytest cleanup.
    for path in folder.iterdir():
        path.chmod(0o600)


def test_setup_rolls_back_partial_files_without_replacing_existing_config(tmp_path):
    setup = script("setup_telegram")
    config = tmp_path / "telegram_config.json"
    config.write_bytes(b"old-config")
    with pytest.raises(setup.SetupError):
        setup.write_config(tmp_path, UUID(int=1), 999, 123456, TOKEN)
    assert config.read_bytes() == b"old-config"
    assert not (tmp_path / "telegram_bot_token").exists()


def test_config_and_token_validation_never_print_secret(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"owner_id": str(UUID(int=1)), "sender_id": 999, "bot_id": 123456}))
    monkeypatch.setenv("JARVIS_TELEGRAM_CONFIG_FILE", str(path))
    monkeypatch.setenv("JARVIS_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.delenv("JARVIS_TELEGRAM_BOT_TOKEN_FILE", raising=False)
    config = load_telegram_config()
    assert load_bot_token(config).get_secret_value() == TOKEN
    monkeypatch.setenv("JARVIS_TELEGRAM_BOT_TOKEN", TOKEN.replace("123456", "987654"))
    with pytest.raises(ConfigurationError, match="does not match") as caught:
        load_bot_token(config)
    assert TOKEN not in str(caught.value)
    path.write_text(
        json.dumps(
            {
                "owner_id": str(UUID(int=1)),
                "sender_id": True,
                "bot_id": 123456,
                "secret": TOKEN,
            }
        )
    )
    with pytest.raises(ConfigurationError) as caught:
        load_telegram_config()
    assert TOKEN not in str(caught.value)


def test_setup_nonce_identity_is_strict_and_ambiguous_accounts_refused():
    setup = script("setup_telegram")

    def row(sender=123, kind="private", date=1000, forwarded=False):
        result = {
            "message": {
                "text": "/jarvis_setup random",
                "date": date,
                "from": {"id": sender, "is_bot": False},
                "chat": {"id": sender, "type": kind},
            }
        }
        if forwarded:
            result["message"]["forward_origin"] = None
        return result

    assert setup.detect_sender([row()], "/jarvis_setup random", 1000) == 123
    for invalid in (row(kind="group"), row(sender=True), row(date=1), row(forwarded=True)):
        assert setup.detect_sender([invalid], "/jarvis_setup random", 1000) is None
    assert setup.detect_sender([row()], "/jarvis_setup different", 1000) is None
    with pytest.raises(setup.SetupError, match="More than one"):
        setup.detect_sender([row(123), row(456)], "/jarvis_setup random", 1000)


def test_setup_refuses_echo_fallback(monkeypatch, tmp_path):
    setup = script("setup_telegram")
    (tmp_path / ".secrets").mkdir()
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: True)

    def unavailable(prompt):
        warnings.warn("no hidden input", setup.getpass.GetPassWarning, stacklevel=1)
        pytest.fail("Input must stop before echo fallback")

    monkeypatch.setattr(setup.getpass, "getpass", unavailable)
    with pytest.raises(setup.SetupError, match="Hidden token entry"):
        setup.setup(tmp_path, UUID(int=1))
    assert list((tmp_path / ".secrets").iterdir()) == []


def test_binary_backup_preserves_bytes_and_failure_removes_partial(tmp_path, monkeypatch):
    backup = script("backup_local")
    content = b"PGDMP\x00\r\n\xffdatabase"

    def fake_run(command, **kwargs):
        assert command[:2] == ["docker", "compose"]
        assert "pg_dump" in command and "--format=custom" in command
        assert "--volumes" not in command
        kwargs["stdout"].write(content)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    path = backup.backup(tmp_path)
    assert path.read_bytes() == content
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(ValueError):
        backup.backup(tmp_path)
    assert list((tmp_path / "backups").iterdir()) == [path]
