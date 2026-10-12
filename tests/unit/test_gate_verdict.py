"""Gate lesson #2: verdict diagnosis + secret scan (offline, stdlib only)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from release_gate import classify
from scan_secrets import scan_tree


def test_verdict_distinguishes_app_from_infra():
    assert classify("ruff_check", 1, "E501 line too long") == "app_failed"
    assert classify("pytest", 0, "") == "passed"
    assert classify("pytest", 1, "FAILED test_x - assert 1 == 2") == "app_failed"
    assert classify("migrate", 1, "connection refused by postgres") == "infra"
    assert classify("bootstrap", 1, "docker daemon unavailable") == "infra"
    assert classify("migrate", 1, "alembic revision constraint failed") == "app_failed"
    # Infra noise plus app evidence still means app.
    assert classify("pytest", 1, "docker warning\nFAILED test_x") == "app_failed"


def test_scan_flags_realistic_shapes_only(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text('key = "sk-or-' + "A" * 24 + '"\n')
    (tmp_path / "src" / "b.py").write_text('token = "jvt1.' + "B" * 24 + '"\n')
    hits = scan_tree(tmp_path)
    assert {(h[0], h[2]) for h in hits} == {
        ("src/a.py", "openrouter_key"),
        ("src/b.py", "jarvis_token"),
    }
    # Values never leave the scanner output.
    assert all("A" * 24 not in str(h) and "B" * 24 not in str(h) for h in hits)


def test_scan_ignores_fixtures_secrets_and_evidence(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(
        'a = "sk-or-private123"\nb = "jvt1.private"\nc = "sk-or-fake"\n'
    )
    (tmp_path / ".secrets").mkdir()
    (tmp_path / ".secrets" / "openrouter_key").write_text("sk-or-" + "C" * 40 + "\n")
    (tmp_path / "docs" / "evidence").mkdir(parents=True)
    (tmp_path / "docs" / "evidence" / "old.log").write_text("sk-or-" + "D" * 40 + "\n")
    assert scan_tree(tmp_path) == []


def test_scan_clean_repo_passes():
    import subprocess

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/scan_secrets.py", "--root", "."],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout
    assert "clean" in result.stdout
