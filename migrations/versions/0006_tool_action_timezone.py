"""Persist source timezone for scheduled tool actions."""

from alembic import op

revision = "0006_tool_action_timezone"
down_revision = "0005_tool_actions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.tool_actions ADD COLUMN due_timezone varchar(64) NOT NULL DEFAULT 'UTC';
    ALTER TABLE app.tool_actions ALTER COLUMN due_timezone DROP DEFAULT;
    ALTER TABLE app.tool_actions ADD CONSTRAINT tool_action_due_timezone_nonempty
      CHECK (length(due_timezone) BETWEEN 1 AND 64 AND due_timezone !~ '[\\r\\n\\x00]');
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
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
       RAISE EXCEPTION 'tool action payload is immutable';
     END IF;
     RETURN NEW;
    END; $$;
    """)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
