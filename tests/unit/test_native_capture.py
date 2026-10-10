"""Actual subprocess checks for the Windows runner's native stream boundary."""

import io
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def host_scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))


@pytest.mark.parametrize("exit_code", [0, 7])
def test_stderr_progress_is_logged_and_real_failure_exit_is_preserved(tmp_path, exit_code):
    from run_test_compose import run_logged

    output = io.BytesIO()
    log = tmp_path / "capture.log"
    code = (
        "import os,sys; "
        "os.write(1,b'stdout\\r\\n'); "
        "os.write(2,b'Image tests Building\\r\\n\\xff'); "
        f"sys.exit({exit_code})"
    )
    actual = run_logged([sys.executable, "-c", code], log, output=output)
    expected = b"stdout\r\nImage tests Building\r\n\xff"
    assert actual == exit_code
    assert log.read_bytes() == output.getvalue() == expected


def test_missing_native_program_cannot_report_success(tmp_path):
    from run_test_compose import run_logged

    with pytest.raises(FileNotFoundError):
        run_logged([str(tmp_path / "does-not-exist")], tmp_path / "capture.log")


def test_log_open_failure_does_not_start_the_native_job(tmp_path):
    from run_test_compose import run_logged

    marker = tmp_path / "started"
    code = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('started')"
    with pytest.raises(OSError):
        run_logged([sys.executable, "-c", code, str(marker)], tmp_path)
    assert not marker.exists()
