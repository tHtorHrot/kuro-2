"""One evidence-producing regression runner. Offline pass never counts as native acceptance."""

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from ops_common import source_fingerprint


def counts(xml):
    if not xml.is_file():
        return None
    root = ET.parse(xml).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    result = {
        name: sum(int(s.get(name, 0)) for s in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }
    result["passed"] = result["tests"] - result["failures"] - result["errors"] - result["skipped"]
    return result


INFRA_MARKERS = (
    "connection refused",
    "connection failed",
    "connection timed out",
    "timed out",
    "no such host",
    "temporary failure",
    "network is unreachable",
    "docker",
    "daemon",
    "operationalerror",
    "nodename nor servname",
)
APP_MARKERS = (
    "traceback",
    "assertionerror",
    "alembic",
    "constraint",
    "already exists",
    "failed",
    "error",
    "mismatch",
    "ruff",
)


def classify(step: str, returncode: int, log_text: str) -> str:
    """passed | app_failed | infra — diagnosis only; exit codes unchanged."""
    if returncode == 0:
        return "passed"
    low = log_text.lower()
    infra = any(marker in low for marker in INFRA_MARKERS)
    app = any(marker in low for marker in APP_MARKERS)
    if step in ("bootstrap", "migrate") and infra and not app:
        return "infra"
    if step == "pytest" and infra and "failed" not in low and "error" not in low:
        return "infra"
    return "app_failed"


def run(mode, root, evidence):
    evidence.mkdir(parents=True, exist_ok=False)
    before = source_fingerprint(root)
    started = datetime.now(UTC).isoformat()
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    steps = [
        ("secret_scan", [sys.executable, "scripts/scan_secrets.py", "--root", "."]),
        (
            "ruff_check",
            [sys.executable, "-m", "ruff", "check", "src", "migrations", "scripts", "tests"],
        ),
        (
            "ruff_format",
            [
                sys.executable,
                "-m",
                "ruff",
                "format",
                "--check",
                "src",
                "migrations",
                "scripts",
                "tests",
            ],
        ),
    ]
    if mode == "native":
        steps += [
            ("bootstrap", [sys.executable, "scripts/bootstrap_test_db.py"]),
            ("upgrade", [sys.executable, "scripts/check_test_upgrade.py"]),
            ("migrate", [sys.executable, "-m", "jarvis.cli", "migrate"]),
            ("migrate", [sys.executable, "-m", "jarvis.cli", "migrate"]),
        ]
        env["JARVIS_REQUIRE_INTEGRATION"] = "1"
        env["JARVIS_TEST_QDRANT"] = "1"
    steps += [
        (
            "pytest",
            [sys.executable, "-m", "pytest", "--junitxml=" + str(evidence / "pytest.xml")]
            + (["-m", "not integration"] if mode == "offline" else []),
        )
    ]
    runs, gate_exit, verdict, failed_step = [], 0, "passed", None
    for number, (name, command) in enumerate(steps, start=1):
        clock = time.monotonic()
        log = evidence / f"{number:02}-command.log"
        with log.open("wb") as output:
            result = subprocess.run(
                command, cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT, check=False
            )
        runs.append(
            {
                "name": name,
                "command": command,
                "exit_code": result.returncode,
                "seconds": round(time.monotonic() - clock, 3),
                "log": log.name,
            }
        )
        print(f"{number}/{len(steps)} {name} exit={result.returncode} log={log.name}", flush=True)
        if result.returncode:
            gate_exit = result.returncode
            failed_step = name
            verdict = classify(name, result.returncode, log.read_text(errors="replace"))
            print(f"verdict={verdict} failed_step={name}", flush=True)
            break
    after = source_fingerprint(root)
    if after["hash"] != before["hash"]:
        gate_exit = gate_exit or 2
        if verdict == "passed":
            verdict, failed_step = "app_failed", "source_changed"
    pytest_log = evidence / f"{len(steps):02}-command.log"
    pytest_text = pytest_log.read_text(errors="replace") if pytest_log.exists() else ""
    item_counts = {}
    for label in ("passed", "failed", "skipped", "deselected", "errors"):
        match = re.search(r"(\d+) " + label + r"\b", pytest_text)
        item_counts[label] = int(match[1]) if match else 0
    subtests = re.search(r"(\d+) subtests passed", pytest_text)
    xml_counts = counts(evidence / "pytest.xml")
    # Pytest's normal-verbosity summary can omit subtests while JUnit emits each one.
    subtests_passed = (
        int(subtests[1])
        if subtests
        else max(0, (xml_counts or {}).get("passed", 0) - item_counts["passed"])
    )
    summary = {
        "mode": mode,
        "started_utc": started,
        "finished_utc": datetime.now(UTC).isoformat(),
        "exit_code": gate_exit,
        "verdict": verdict,
        "failed_step": failed_step,
        "commands": runs,
        "xml_testcases": xml_counts,
        "pytest_items": item_counts,
        "subtests_passed": subtests_passed,
        "subtest_count_method": "terminal summary or extra passed JUnit cases beyond pytest items",
        "source": before,
        "source_unchanged": before["hash"] == after["hash"],
        "schema": "0017_task_role_documents",
        "environment": {
            "python": platform.python_version(),
            "system": platform.platform(),
            "docker": shutil.which("docker"),
            "postgres": shutil.which("postgres"),
            "dependencies": {
                p: importlib.metadata.version(p)
                for p in ["pytest", "psycopg", "sqlalchemy", "alembic", "ruff"]
            },
        },
        "native_integration": "tested" if mode == "native" and not gate_exit else "not_run",
        "live_google_telegram": "not_run",
        "limitations": (
            "Offline excludes native integration; OCR runs when present. Docker/restore/live "
            "results are not implied."
            if mode == "offline"
            else "Native includes mocked providers; no live write or full encrypted restore "
            "implied."
        ),
    }
    (evidence / "verification.json").write_text(json.dumps(summary, indent=2) + "\n")
    return gate_exit


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["offline", "native"], default="offline")
    p.add_argument("--evidence", type=Path, required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    raise SystemExit(run(args.mode, root, args.evidence.resolve()))
