"""Immutable foundation schema; owner isolation and append-only audit permissions."""

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

DDL = """
CREATE SCHEMA app;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO jarvis_app;

CREATE FUNCTION app.current_owner_id() RETURNS uuid
LANGUAGE sql STABLE SET search_path = pg_catalog
AS $$ SELECT NULLIF(current_setting('jarvis.owner_id', true), '')::uuid $$;
REVOKE ALL ON FUNCTION app.current_owner_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.current_owner_id() TO jarvis_app;

CREATE TABLE app.users (
  id uuid PRIMARY KEY,
  display_name varchar(100) NOT NULL,
  timezone varchar(64) NOT NULL,
  status varchar(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app.api_tokens (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES app.users(id),
  secret_digest bytea NOT NULL CHECK (octet_length(secret_digest)=32),
  label varchar(80) NOT NULL,
  scopes text[] NOT NULL CHECK (cardinality(scopes)>0),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_api_tokens_owner_id ON app.api_tokens(owner_id);
CREATE INDEX ix_api_tokens_expires_at ON app.api_tokens(expires_at);

CREATE TABLE app.pairing_codes (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES app.users(id),
  secret_digest bytea NOT NULL CHECK (octet_length(secret_digest)=32),
  expected_sender_id bigint NOT NULL CHECK (expected_sender_id>0),
  expires_at timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0 AND attempts<=5),
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_pairing_codes_owner_id ON app.pairing_codes(owner_id);

CREATE TABLE app.external_identities (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES app.users(id),
  channel varchar(32) NOT NULL CHECK (channel='telegram'),
  external_user_id bigint NOT NULL CHECK (external_user_id>0),
  chat_id bigint NOT NULL CHECK (chat_id=external_user_id),
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT identity_channel_user UNIQUE(channel,external_user_id),
  CONSTRAINT identity_owner_channel UNIQUE(owner_id,channel)
);
CREATE INDEX ix_external_identities_owner_id ON app.external_identities(owner_id);

CREATE TABLE app.audit_events (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES app.users(id),
  actor_id uuid,
  action varchar(64) NOT NULL,
  resource_id uuid,
  metadata_safe jsonb NOT NULL DEFAULT '{}',
  request_id varchar(36),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_events_owner_id ON app.audit_events(owner_id,created_at DESC);

REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON app.users,app.api_tokens,app.pairing_codes,
  app.external_identities TO jarvis_app;
GRANT SELECT,INSERT ON app.audit_events TO jarvis_app;
GRANT SELECT ON public.jarvis_schema_version TO jarvis_app;
"""


def upgrade():
    op.execute(DDL)
    for table, key in [
        ("users", "id"),
        ("api_tokens", "owner_id"),
        ("pairing_codes", "owner_id"),
        ("external_identities", "owner_id"),
        ("audit_events", "owner_id"),
    ]:
        # Identifiers come from this fixed source list, never external input.
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_isolation ON app.{table} "
            f"USING ({key} = app.current_owner_id()) "
            f"WITH CHECK ({key} = app.current_owner_id())"
        )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
