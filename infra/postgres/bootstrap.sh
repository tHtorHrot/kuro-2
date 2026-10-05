#!/bin/sh
# Official image invokes this only when initializing an empty data directory.
set -eu
# Accept legacy CRLF files from the Windows v0.1.0 generator.
# Generated secrets use URL-safe ASCII; CR/LF are file terminators, never password data.
export JARVIS_APP_PASSWORD="$(tr -d '\r\n' < /run/secrets/app_password)"
export JARVIS_MIGRATOR_PASSWORD="$(tr -d '\r\n' < /run/secrets/migrator_password)"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password JARVIS_APP_PASSWORD
\getenv migrator_password JARVIS_MIGRATOR_PASSWORD
\getenv database_name POSTGRES_DB
CREATE ROLE jarvis_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD :'migrator_password';
CREATE ROLE jarvis_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD :'app_password';
REVOKE ALL ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO jarvis_app, jarvis_migrator;
GRANT CREATE ON DATABASE :"database_name" TO jarvis_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO jarvis_migrator;
GRANT USAGE ON SCHEMA public TO jarvis_app;
SQL
unset JARVIS_APP_PASSWORD JARVIS_MIGRATOR_PASSWORD
