"""Restore only to a NEW disposable project. No executor, transport, cloud worker or secrets."""

import argparse
import json
import re
import shutil
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from ops_backup import cms_file, verify_bundle
from ops_common import Compose, OpsError, private_folder, sha256

RESTORE_DB = "jarvis_restore_test"
PROBE_SQL = """
SELECT json_build_object(
 'schema',(SELECT version_num FROM public.jarvis_schema_version),
 'owners',(SELECT count(*) FROM app.users),
 'identities',(SELECT count(*) FROM app.external_identities),
 'profile_memory',(SELECT count(*) FROM app.profile_memory),
 'projects',(SELECT count(*) FROM app.projects),
 'documents',(SELECT count(*) FROM app.documents),
 'chunks',(SELECT count(*) FROM app.document_chunks),
 'drafts',(SELECT count(*) FROM app.calendar_tasks),
 'results',(SELECT count(*) FROM app.tool_actions WHERE result IS NOT NULL),
 'notifications',(SELECT count(*) FROM app.calendar_notifications),
 'receipts',(SELECT count(*) FROM app.telegram_receipts),
 'actions',(SELECT json_object_agg(status,n) FROM
  (SELECT status,count(*) n FROM app.tool_actions GROUP BY status) counts)
);
"""
QUARANTINE_SQL = """
-- Restore clone is already network-isolated with no execution/transport services.
UPDATE app.assistant_state SET enabled=false, frozen=true;
UPDATE app.tool_grants SET enabled=false;
UPDATE app.tool_actions SET status='uncertain',finished_at=now(),
 lease_token=NULL,lease_until=NULL,error_code='restore_dispatch_requires_reconciliation'
 WHERE status='dispatching';
UPDATE app.tool_actions SET status='queued',lease_token=NULL,lease_until=NULL
 WHERE status='claimed';
UPDATE app.telegram_receipts SET delivery_status='uncertain',reply_text=NULL
 WHERE delivery_status='sending';
UPDATE app.calendar_notifications SET delivery_status='uncertain',reply_text=NULL
 WHERE delivery_status='sending';
"""


def validate_project(project):
    if not re.fullmatch(r"kuro-restore-[a-z0-9][a-z0-9-]{0,35}", project):
        raise OpsError("Restore project must start kuro-restore-; production targets forbidden")


def validate_restore_config(root):
    # Exact standalone configuration: no user-provided Compose overlays are accepted.
    import yaml

    config = yaml.safe_load((root / "compose.restore.yaml").read_text())
    if set(config["services"]) != {"postgres", "restore-files"}:
        raise OpsError("Restore config must contain only PostgreSQL and volume helper")
    for service in config["services"].values():
        if service.get("ports") or service.get("secrets") or service.get("env_file"):
            raise OpsError("Restore must not expose ports or mount production secrets")
        if service.get("network_mode") not in (None, "none"):
            raise OpsError("Restore helper network forbidden")
    if any(not n.get("internal") for n in config["networks"].values()):
        raise OpsError("Restore networks must be internal")
    if config["services"]["postgres"]["environment"]["POSTGRES_DB"] != RESTORE_DB:
        raise OpsError("Restore DB must be disposable *_test")


def drill(
    root,
    encrypted,
    checksum,
    project,
    *,
    report_path,
    certificate,
    certificate_sha256,
    private_key,
    passphrase_file=None,
):
    validate_project(project)
    validate_restore_config(root)
    if not shutil.which("docker") or not shutil.which("openssl"):
        raise OpsError("Docker/OpenSSL required; no restore side effects occurred")
    if sha256(encrypted) != checksum:
        raise OpsError("Encrypted archive checksum mismatch")
    compose = Compose(root, project, ["compose.restore.yaml"])
    if compose.ps():
        raise OpsError("Restore project already has containers; choose a NEW disposable project")
    started, touched = time.monotonic(), False
    folder = private_folder(report_path.parent)
    with tempfile.TemporaryDirectory(prefix="kuro-restore-private-", dir=folder) as temporary:
        temp = private_folder(temporary)
        bundle = temp / "bundle.tar"
        cms_file(
            encrypted,
            bundle,
            certificate=certificate,
            certificate_sha256=certificate_sha256,
            private_key=private_key,
            passphrase_file=passphrase_file,
        )
        parts = temp / "parts"
        manifest = verify_bundle(bundle, parts)
        if manifest["schema"] != "0017_task_role_documents":
            raise OpsError("This restore runner requires schema 0017; use matching release tooling")
        try:
            touched = True
            compose.run("up", "-d", "--wait", "postgres", timeout=120)
            # Fresh test roles preserve table ownership and FORCE RLS; runtime is never superuser.
            compose.sql(
                "CREATE ROLE jarvis_migrator LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT "
                "PASSWORD 'restore-test-migrator'; "
                "CREATE ROLE jarvis_app LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT "
                "PASSWORD 'restore-test-app'; "
                "REVOKE ALL ON DATABASE jarvis_restore_test FROM PUBLIC; "
                "GRANT CONNECT ON DATABASE jarvis_restore_test TO jarvis_app,jarvis_migrator; "
                "GRANT CREATE ON DATABASE jarvis_restore_test TO jarvis_migrator; "
                "REVOKE ALL ON SCHEMA public FROM PUBLIC; "
                "GRANT USAGE,CREATE ON SCHEMA public TO jarvis_migrator; "
                "GRANT USAGE ON SCHEMA public TO jarvis_app;",
                database=RESTORE_DB,
            )
            with (parts / "database.dump").open("rb") as source:
                compose.run(
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "-U",
                    "postgres",
                    "--role",
                    "jarvis_migrator",
                    "-d",
                    RESTORE_DB,
                    "--no-owner",
                    "--exit-on-error",
                    input_stream=source,
                    timeout=600,
                )
            restored = json.loads(compose.sql(PROBE_SQL, database=RESTORE_DB))
            if restored["schema"] != manifest["schema"]:
                raise OpsError("Restored schema mismatch")
            with (parts / "volumes.tar").open("rb") as source:
                compose.run(
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "restore-files",
                    input_stream=source,
                    timeout=600,
                )
            # Quarantine before any possible activation. Original grants/identities/pepper aren't
            # rotated. Claimed jobs remain queued for review; in-flight effects stay uncertain.
            compose.sql(QUARANTINE_SQL, database=RESTORE_DB)
            report = {
                "status": "restored_quarantined",
                "project": project,
                "restored_at_utc": datetime.now(UTC).isoformat(),
                "restore_seconds": round(time.monotonic() - started, 3),
                "data_loss_window_seconds": None,
                "backup_boundary": manifest["consistency_boundary_utc"],
                "schema": manifest["schema"],
                "encrypted_sha256": checksum,
                "before_quarantine": restored,
                "after_quarantine": json.loads(compose.sql(PROBE_SQL, database=RESTORE_DB)),
                "executor": "not_present",
                "external_transports": "not_present",
                "secret_recovery": "not_activated; private original credentials required",
                "retrieval_drill": "not_run; verify cold Qdrant/model byte recovery and queries "
                "on this isolated clone before any activation",
                "reconciliation": "required; restore does not undo Google events",
            }
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            return report
        finally:
            if touched:
                compose.run("stop", "--timeout", "30", "postgres", timeout=60)
                # Volumes retained for review. Never call down --volumes on production.


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--sha256", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--recipient-cert", type=Path, required=True)
    p.add_argument("--cert-sha256", required=True)
    p.add_argument("--private-key", type=Path, required=True)
    p.add_argument("--key-passphrase-file", type=Path)
    p.add_argument("--report", type=Path, default=Path("backups/restore-drill.json"))
    args = p.parse_args()
    print(
        json.dumps(
            drill(
                Path(__file__).resolve().parents[1],
                args.archive,
                args.sha256,
                args.project,
                report_path=args.report,
                certificate=args.recipient_cert,
                certificate_sha256=args.cert_sha256,
                private_key=args.private_key,
                passphrase_file=args.key_passphrase_file,
            )
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OpsError, OSError, ValueError, tarfile.TarError):
        raise SystemExit(
            "Restore blocked/failed. Check isolated project and private recovery key."
        ) from None
