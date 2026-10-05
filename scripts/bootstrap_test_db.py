"""Provision roles in a NEW, disposable *_test database; never production."""

import os

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def main() -> None:
    admin = os.environ["JARVIS_TEST_ADMIN_URL"]
    app = make_url(os.environ["JARVIS_TEST_DATABASE_URL"])
    migrator = make_url(os.environ["JARVIS_MIGRATION_DATABASE_URL"])
    admin_parts = make_url(admin)
    urls = [admin_parts, app, migrator]
    if any(not (url.database or "").endswith("_test") for url in urls):
        raise SystemExit("Refusing to operate outside a disposable *_test database")
    if len({(u.host, u.port, u.database) for u in urls}) != 1:
        raise SystemExit("All test URLs must target the same isolated database")
    if app.username != "jarvis_app" or migrator.username != "jarvis_migrator":
        raise SystemExit("Unexpected test role names")
    with psycopg.connect(admin, autocommit=True) as connection:
        if connection.execute("SELECT to_regnamespace('app')").fetchone()[0] is not None:
            raise SystemExit("Test database is not empty. Use a fresh disposable cluster.")
        for url in (migrator, app):
            exists = connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (url.username,)
            ).fetchone()
            if exists:
                raise SystemExit("Test role already exists. Use a fresh disposable cluster.")
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOBYPASSRLS NOINHERIT PASSWORD {}"
                ).format(sql.Identifier(url.username), sql.Literal(url.password))
            )
        db = sql.Identifier(app.database)
        connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO jarvis_app, jarvis_migrator").format(db)
        )
        connection.execute(sql.SQL("GRANT CREATE ON DATABASE {} TO jarvis_migrator").format(db))
        connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        connection.execute("GRANT USAGE, CREATE ON SCHEMA public TO jarvis_migrator")
        connection.execute("GRANT USAGE ON SCHEMA public TO jarvis_app")
    print("Disposable test database roles provisioned")


if __name__ == "__main__":
    main()
