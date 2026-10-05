import importlib.util
import subprocess
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "documents.py"
    spec = importlib.util.spec_from_file_location("documents_script", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_upload_preserves_binary_and_child_exit_status(tmp_path):
    source = tmp_path / "-laporan & contoh.docx"
    content = bytes(range(256)) + b"\r\n\x00\xff"
    source.write_bytes(content)

    def runner(command, **kwargs):
        assert kwargs["stdin"].read() == content and kwargs.get("shell", False) is False
        assert "--filename=-laporan & contoh.docx" in command
        assert command[-4:] == ["--data-class", "restricted", "--ocr", "always"]
        assert "-T" in command and "--no-deps" in command
        return subprocess.CompletedProcess(command, 7)

    result = module().run(
        ["add", str(source), "--data-class", "restricted", "--ocr", "always"], runner=runner
    )
    assert result == 7


def test_upload_missing_file_stops_before_docker(tmp_path):
    def runner(*args, **kwargs):
        pytest.fail("Docker must not start for missing input")

    with pytest.raises(ValueError, match="File"):
        module().run(["add", str(tmp_path / "missing.pdf")], runner=runner)


def test_invalid_id_rejected_before_docker():
    with pytest.raises(SystemExit) as exc:
        module().run(["delete", "../../not-an-id"])
    assert exc.value.code == 2


def test_status_without_upload():
    def runner(command, **kwargs):
        assert command[-1] == "knowledge-status" and "stdin" not in kwargs
        return subprocess.CompletedProcess(command, 0)

    assert module().run(["status"], runner=runner) == 0
