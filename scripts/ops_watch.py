"""Local alarm/recovery log with dedup. External alert adapter is operator-selected and disabled."""

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from ops_common import Compose, OpsError, private_folder


def alarm_codes(snapshot, *, backup_age=None, disk_free=None, ram_available=None):
    codes = set()
    if not snapshot.get("database_ready"):
        codes.add("database_unready")
    for name, worker in snapshot.get("heartbeat", {}).items():
        if worker["expected"] and not worker["recent"]:
            codes.add("worker_stale:" + name)
    if snapshot.get("due_age_seconds") is not None and snapshot["due_age_seconds"] > 120:
        codes.add("due_actions_stale")
    for status in ("failed", "uncertain"):
        if snapshot.get("actions", {}).get(status, 0):
            codes.add("actions:" + status)
    if snapshot.get("stale_leases", 0):
        codes.add("leases_stale")
    if snapshot.get("delivery_backlog", 0) > 50:
        codes.add("delivery_backlog")
    if snapshot.get("documents", {}).get("failed", 0):
        codes.add("knowledge_failed")
    if backup_age is None or backup_age > 86400:
        codes.add("backup_missing_or_old")
    if disk_free is not None and disk_free < 1024**3:
        codes.add("disk_low")
    if ram_available is not None and ram_available < 256 * 1024**2:
        codes.add("ram_low")
    return codes


def transitions(previous, current, timestamp):
    return [
        {"code": code, "state": "alarm", "at_utc": timestamp} for code in sorted(current - previous)
    ] + [
        {"code": code, "state": "recovered", "at_utc": timestamp}
        for code in sorted(previous - current)
    ]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default="personal-jarvis")
    p.add_argument("--compose", action="append", required=True)
    p.add_argument("--owner-id", required=True)
    p.add_argument("--interval", type=int, default=30)
    p.add_argument("--once", action="store_true")
    p.add_argument("--state-dir", type=Path, default=Path("operations"))
    p.add_argument("--backup-dir", type=Path, default=Path("backups/encrypted"))
    p.add_argument(
        "--alert-command-json", help="Explicit argv array; JSON event on stdin; no shell"
    )
    args = p.parse_args()
    if not 5 <= args.interval <= 60:
        raise OpsError("Interval must be 5..60 seconds")
    root = Path(__file__).resolve().parents[1]
    compose = Compose(root, args.project, args.compose)
    folder = private_folder(args.state_dir)
    state_path, log_path = folder / "monitor-state.json", folder / "alarms.jsonl"
    previous = set(json.loads(state_path.read_text())) if state_path.exists() else set()
    adapter = json.loads(args.alert_command_json) if args.alert_command_json else None
    if adapter is not None and (
        not isinstance(adapter, list) or not adapter or any(type(v) is not str for v in adapter)
    ):
        raise OpsError("Alert adapter must be an explicit argv array")
    while True:
        now = datetime.now(UTC)
        try:
            raw = compose.run(
                "run",
                "--rm",
                "--no-deps",
                "ops",
                "ops-monitor",
                "--owner-id",
                args.owner_id,
                timeout=20,
            )
            health = json.loads(raw)
        except (OpsError, ValueError):
            health = {"database_ready": False}
        latest = None
        for path in args.backup_dir.glob("kuro-complete-*.json"):
            try:
                report = json.loads(path.read_text())
                if report.get("encrypted") and report.get("completed_utc"):
                    date = datetime.fromisoformat(report["completed_utc"])
                    latest = max(latest, date) if latest else date
            except (OSError, ValueError):
                continue
        ram = None
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    ram = int(line.split()[1]) * 1024
        current = alarm_codes(
            health,
            backup_age=(now - latest).total_seconds() if latest else None,
            disk_free=shutil.disk_usage(root).free,
            ram_available=ram,
        )
        events = transitions(previous, current, now.isoformat())
        for event in events:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(event) + "\n")
            if adapter:
                try:
                    result = subprocess.run(
                        adapter,
                        input=json.dumps(event).encode(),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        check=False,
                    )
                    if result.returncode:
                        raise OpsError("Local alert adapter failed")
                except (OSError, subprocess.SubprocessError):
                    raise OpsError("Local alert adapter failed") from None
        state_path.write_text(json.dumps(sorted(current)) + "\n")
        print(
            json.dumps(
                {
                    "alarms": sorted(current),
                    "changes": len(events),
                    "external_adapter": "configured" if adapter else "disabled",
                }
            ),
            flush=True,
        )
        previous = current
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except (OpsError, OSError, ValueError):
        raise SystemExit(
            "Monitor failed; details withheld. Check local operations state."
        ) from None
