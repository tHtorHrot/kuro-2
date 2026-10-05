import importlib.util
import json
import logging
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.core.config import ConfigurationError, Settings, load_settings, read_secret
from jarvis.core.logging import SafeJsonFormatter


@pytest.mark.parametrize(
    "changes",
    [
        {"database_url": "sqlite:///test.db"},
        {"database_url": "postgresql+psycopg://postgres:test@localhost/jarvis_test"},
        {"token_pepper": "short-secret-must-not-leak"},
        {"allowed_hosts": ["*"]},
        {"default_timezone": "Missing/Timezone"},
        {"environment": "production", "docs_enabled": True},
        {"environment": "production", "log_level": "DEBUG"},
        {"premium_mode": "automatic"},
        {"cloud_privacy": "allow_training"},
    ],
)
def test_unsafe_configuration_fails(settings, changes):
    with pytest.raises(ValidationError) as error:
        Settings(**(settings.model_dump() | changes))
    assert "short-secret-must-not-leak" not in str(error.value)


def test_file_secret_and_ambiguous_sources(monkeypatch, tmp_path):
    path = tmp_path / "credential"
    path.write_text("secret-value\n")
    monkeypatch.setenv("TEST_SECRET_FILE", str(path))
    assert read_secret("TEST_SECRET") == "secret-value"
    monkeypatch.setenv("TEST_SECRET", "different-value")
    with pytest.raises(ConfigurationError) as error:
        read_secret("TEST_SECRET")
    assert "secret-value" not in str(error.value)
    assert "different-value" not in str(error.value)


def test_missing_or_large_secret_file_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_SECRET_FILE", str(tmp_path / "missing"))
    with pytest.raises(ConfigurationError):
        read_secret("TEST_SECRET")
    path = tmp_path / "oversized"
    path.write_text("a" * 16385)
    monkeypatch.setenv("TEST_SECRET_FILE", str(path))
    with pytest.raises(ConfigurationError):
        read_secret("TEST_SECRET")


def test_load_settings_never_echoes_invalid_credentials(monkeypatch):
    monkeypatch.delenv("JARVIS_DATABASE_URL_FILE", raising=False)
    monkeypatch.delenv("JARVIS_TOKEN_PEPPER_FILE", raising=False)
    monkeypatch.setenv("JARVIS_DATABASE_URL", "bad-url-CONFIDENTIAL")
    monkeypatch.setenv("JARVIS_TOKEN_PEPPER", "secret")
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "CONFIDENTIAL" not in str(error.value)


def test_logs_drop_payloads_and_exception_detail():
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        "",
        1,
        "Bearer token-value postgres-password https://example.test/confidential",
        (),
        (ValueError, ValueError("document content confidential"), None),
    )
    record.document_text = "private-upload"
    rendered = SafeJsonFormatter(["postgres-password"]).format(record)
    assert json.loads(rendered)["error_type"] == "ValueError"
    for value in (
        "token-value",
        "postgres-password",
        "example.test",
        "confidential",
        "private-upload",
    ):
        assert value not in rendered


def test_secret_generator_refuses_overwrite_and_prints_nothing(tmp_path, capsys):
    path = Path(__file__).resolve().parents[2] / "scripts" / "setup_local.py"
    spec = importlib.util.spec_from_file_location("setup_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.create_secrets(tmp_path)
    folder = tmp_path / ".secrets"
    initial = (folder / "token_pepper").read_bytes()
    assert len(initial.strip()) >= 43
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    with pytest.raises(FileExistsError):
        module.create_secrets(tmp_path)
    assert (folder / "token_pepper").read_bytes() == initial
    assert capsys.readouterr().out == ""
