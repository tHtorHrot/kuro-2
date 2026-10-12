"""Exercise 2B -> 4B on a freshly bootstrapped, disposable native test database."""

import os
from uuid import uuid4

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


def main():
    url = make_url(os.environ["JARVIS_TEST_DATABASE_URL"])
    migration = make_url(os.environ["JARVIS_MIGRATION_DATABASE_URL"])
    if (
        not (url.database or "").endswith("_test")
        or url.username != "jarvis_app"
        or migration.username != "jarvis_migrator"
        or (url.host, url.port, url.database)
        != (migration.host, migration.port, migration.database)
    ):
        raise SystemExit("Only disposable *_test databases with test roles are allowed")
    connection_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    command.upgrade(Config("alembic.ini"), "0003_assistant")
    owner, identity, conversation = uuid4(), uuid4(), uuid4()
    with psycopg.connect(connection_url) as db:
        db.execute("SELECT set_config('jarvis.owner_id', %s, true)", (str(owner),))
        db.execute(
            "INSERT INTO app.users(id,display_name,timezone) VALUES (%s,'Upgrade fixture','UTC')",
            (owner,),
        )
        db.execute(
            "INSERT INTO app.telegram_state(owner_id,bot_id,rate_window_at) "
            "VALUES (%s,987654321,now())",
            (owner,),
        )
        db.execute(
            "INSERT INTO app.external_identities(id,owner_id,channel,external_user_id,chat_id) "
            "VALUES (%s,%s,'telegram',987654321,987654321)",
            (identity, owner),
        )
        db.execute(
            "INSERT INTO app.assistant_state(owner_id,conversation_id,config_hash,enabled) "
            "VALUES (%s,%s,'existing-fingerprint',true)",
            (owner, conversation),
        )
        db.execute(
            "INSERT INTO app.profile_memory(owner_id,key,value) "
            "VALUES (%s,'fixture','keep-existing-memory')",
            (owner,),
        )
    command.upgrade(Config("alembic.ini"), "0008_executor_binding")
    statuses = ("awaiting_approval", "queued", "claimed", "dispatching", "uncertain")
    action_ids = [uuid4() for _ in statuses]
    document = uuid4()
    with psycopg.connect(connection_url) as db:
        db.execute("SELECT set_config('jarvis.owner_id', %s, true)", (str(owner),))
        db.execute(
            "INSERT INTO app.documents(id,owner_id,title,kind,data_class,pipeline,ocr,"
            "status,byte_size) "
            "VALUES (%s,%s,'Existing document','pdf','private','fixture','never','queued',42)",
            (document, owner),
        )
        db.execute(
            "INSERT INTO app.tool_grants(owner_id,agent,scopes,enabled,revision) "
            "VALUES (%s,'calendar',ARRAY['calendar:read','calendar:write'],true,7)",
            (owner,),
        )
        for action_id, status in zip(action_ids, statuses, strict=True):
            db.execute(
                "INSERT INTO app.tool_actions(id,owner_id,agent,tool_name,effect,arguments,"
                "action_fingerprint,status,authorization_reason,due_at,due_timezone,grant_revision,"
                "spec_fingerprint,lease_token,lease_until,approval_expires_at) VALUES "
                "(%s,%s,'calendar','calendar_create_event','reversible_write',%s::jsonb,%s,%s,"
                "'write_not_authorized',now()+interval '1 day','UTC',7,%s,%s,"
                "now()+interval '90 seconds',now()+interval '5 minutes')",
                (
                    action_id,
                    owner,
                    '{"title":"Preserve pending"}',
                    "a" * 64,
                    status,
                    "b" * 64,
                    uuid4(),
                ),
            )
    command.upgrade(Config("alembic.ini"), "head")
    with psycopg.connect(connection_url) as db:
        db.execute("SELECT set_config('jarvis.owner_id', %s, true)", (str(owner),))
        assert (
            db.execute("SELECT version_num FROM public.jarvis_schema_version").fetchone()[0]
            == "0017_task_role_documents"
        )
        assert db.execute("SELECT id,title FROM app.documents").fetchone() == (
            document,
            "Existing document",
        )
        saved = dict(db.execute("SELECT id,status FROM app.tool_actions").fetchall())
        assert saved == dict(zip(action_ids, statuses, strict=True))
        assert (
            db.execute(
                "SELECT count(*) FROM app.tool_actions WHERE fingerprint_version=1"
            ).fetchone()[0]
            == 5
        )
        assert db.execute("SELECT revision FROM app.tool_grants").fetchone()[0] == 7
        assert db.execute("SELECT count(*) FROM app.calendar_tasks").fetchone()[0] == 0
        assert db.execute(
            "SELECT enabled, config_hash, conversation_id FROM app.assistant_state"
        ).fetchone() == (True, "existing-fingerprint", conversation)
        assert db.execute("SELECT id,enabled FROM app.external_identities").fetchone() == (
            identity,
            True,
        )
        assert db.execute("SELECT value,kind,status FROM app.profile_memory").fetchone() == (
            "keep-existing-memory",
            "profile",
            "active",
        )
        # Stage 6 slice 3: projects registry exists, empty, RLS forced; memory project nullable.
        assert db.execute("SELECT count(*) FROM app.projects").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM app.project_state").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid "
                "WHERE n.nspname='app' AND c.relname IN ('projects','project_state') "
                "AND c.relrowsecurity AND c.relforcerowsecurity"
            ).fetchone()[0]
            == 2
        )
        assert (
            db.execute(
                "SELECT is_nullable FROM information_schema.columns WHERE table_schema='app' "
                "AND table_name='profile_memory' AND column_name='project'"
            ).fetchone()[0]
            == "YES"
        )
        # Stage 7 documents: role baru lolos CHECK, role lama tetap ada.
        task_id = uuid4()
        db.execute(
            "INSERT INTO app.tasks(id,owner_id,title,role,status) "
            "VALUES (%s,%s,'doc check','documents','queued')",
            (task_id, owner),
        )
        assert (
            db.execute("SELECT role FROM app.tasks WHERE id=%s", (task_id,)).fetchone()[0]
            == "documents"
        )
    print(
        "Populated stage 2B -> 4B native migration: "
        "existing owner, identity, enablement and memory preserved"
    )


if __name__ == "__main__":
    main()
