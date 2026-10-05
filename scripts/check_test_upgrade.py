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
    command.upgrade(Config("alembic.ini"), "head")
    with psycopg.connect(connection_url) as db:
        db.execute("SELECT set_config('jarvis.owner_id', %s, true)", (str(owner),))
        assert (
            db.execute("SELECT version_num FROM public.jarvis_schema_version").fetchone()[0]
            == "0008_executor_binding"
        )
        assert db.execute(
            "SELECT enabled, config_hash, conversation_id FROM app.assistant_state"
        ).fetchone() == (True, "existing-fingerprint", conversation)
        assert db.execute("SELECT id,enabled FROM app.external_identities").fetchone() == (
            identity,
            True,
        )
        assert (
            db.execute("SELECT value FROM app.profile_memory").fetchone()[0]
            == "keep-existing-memory"
        )
    print(
        "Populated stage 2B -> 4B native migration: "
        "existing owner, identity, enablement and memory preserved"
    )


if __name__ == "__main__":
    main()
