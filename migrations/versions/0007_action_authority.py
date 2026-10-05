"""Current grants, deduplication and bounded durable tool results."""

from alembic import op

revision = "0007_action_authority"
down_revision = "0006_tool_action_timezone"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.tool_grants (
      owner_id uuid NOT NULL REFERENCES app.users(id),
      agent varchar(80) NOT NULL,
      scopes text[] NOT NULL,
      enabled boolean NOT NULL DEFAULT false,
      revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(owner_id, agent)
    );
    REVOKE ALL ON app.tool_grants FROM PUBLIC;
    GRANT SELECT,INSERT,UPDATE ON app.tool_grants TO jarvis_app;
    ALTER TABLE app.tool_grants ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.tool_grants FORCE ROW LEVEL SECURITY;
    CREATE POLICY owner_isolation ON app.tool_grants
      USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());
    ALTER TABLE app.tool_actions
      ADD COLUMN source_key varchar(200),
      ADD COLUMN grant_revision integer,
      ADD COLUMN spec_fingerprint varchar(64),
      ADD COLUMN result jsonb,
      ADD COLUMN error_code varchar(80),
      ADD CONSTRAINT tool_result_bound CHECK (octet_length(result::text)<=32768),
      ADD CONSTRAINT tool_action_source_unique UNIQUE(owner_id,source_key);
    -- Old actions have no durable grant. Never silently grant them new authority.
    ALTER TABLE app.tool_actions NO FORCE ROW LEVEL SECURITY;
    UPDATE app.tool_actions SET status='cancelled', finished_at=now(),
      lease_token=NULL, lease_until=NULL, error_code='legacy_authority_missing'
      WHERE status IN ('queued','claimed','awaiting_approval');
    UPDATE app.tool_actions SET status='uncertain', finished_at=now(),
      lease_token=NULL, lease_until=NULL, error_code='legacy_dispatch_uncertain'
      WHERE status='dispatching';
    ALTER TABLE app.tool_actions FORCE ROW LEVEL SECURITY;
    CREATE OR REPLACE FUNCTION app.reject_tool_action_payload_update() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
      IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
        OR NEW.request_id IS DISTINCT FROM OLD.request_id
        OR NEW.agent IS DISTINCT FROM OLD.agent
        OR NEW.tool_name IS DISTINCT FROM OLD.tool_name
        OR NEW.effect IS DISTINCT FROM OLD.effect
        OR NEW.arguments IS DISTINCT FROM OLD.arguments
        OR NEW.action_fingerprint IS DISTINCT FROM OLD.action_fingerprint
        OR NEW.due_at IS DISTINCT FROM OLD.due_at
        OR NEW.due_timezone IS DISTINCT FROM OLD.due_timezone
        OR NEW.source_key IS DISTINCT FROM OLD.source_key
        OR NEW.grant_revision IS DISTINCT FROM OLD.grant_revision
        OR NEW.spec_fingerprint IS DISTINCT FROM OLD.spec_fingerprint
        OR NEW.authorization_reason IS DISTINCT FROM OLD.authorization_reason
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'tool action payload is immutable';
      END IF;
      RETURN NEW;
    END; $$;
    """)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
