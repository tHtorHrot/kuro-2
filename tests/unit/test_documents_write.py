"""Stage 7 Documents: validasi payload murni (offline)."""

import pytest

from jarvis.orchestration.contracts import TaskError
from jarvis.specialists.documents import MAX_WRITE_BYTES, validate_write_input


def test_valid_payload_returns_path_and_bytes():
    path, data = validate_write_input({"path": "catatan.md", "content": "halo"})
    assert path == "catatan.md" and data == b"halo"


@pytest.mark.parametrize(
    "acceptance",
    [
        None,
        {},
        {"path": "a.md"},
        {"content": "x"},
        {"path": 123, "content": "x"},
        {"path": "/abs.md", "content": "x"},
        {"path": "../escape.md", "content": "x"},
        {"path": "a.exe", "content": "x"},
        {"path": "a.md", "content": ""},
        {"path": "a.md", "content": "x" * (MAX_WRITE_BYTES + 1)},
    ],
)
def test_invalid_payload_rejected(acceptance):
    with pytest.raises(TaskError):
        validate_write_input(acceptance)
