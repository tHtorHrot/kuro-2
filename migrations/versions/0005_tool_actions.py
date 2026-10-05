"""Durable owner-scoped tool action journal and scheduler queue."""

from alembic import op

revision = "0005_tool_actions"
down_revision = "0004_knowledge"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE app.tool_actions (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL REFERENCES app.users(id),
 request_id uuid,
 agent varchar(80) NOT NULL,
 tool_name varchar(80) NOT NULL,
 effect varchar(24) NOT NULL CHECK
   (effect IN ('read','reversible_write','external_send','destructive','high_impact')),
 arguments jsonb NOT NULL CHECK (octet_length(arguments::text)<=32768),
 action_fingerprint varchar(64) NOT NULL CHECK (action_fingerprint ~ '^[0-9a-f]{64}$'),
 status varchar(24) NOT NULL CHECK
   (status IN ('awaiting_approval','queued','claimed','dispatching','succeeded','failed',
               'uncertain','cancelled')),
 authorization_reason varchar(40) NOT NULL,
 approval_expires_at timestamptz,
 approved_at timestamptz,
 due_at timestamptz NOT NULL,
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
 lease_token uuid,
 lease_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,request_id) REFERENCES app.assistant_requests(owner_id,id)
);
CREATE INDEX ix_tool_action_queue ON app.tool_actions(owner_id,status,due_at,lease_until);
CREATE INDEX ix_tool_action_request ON app.tool_actions(owner_id,request_id);
REVOKE ALL ON app.tool_actions FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON app.tool_actions TO jarvis_app;
ALTER TABLE app.tool_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.tool_actions FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON app.tool_actions
 USING (owner_id=app.current_owner_id())
 WITH CHECK (owner_id=app.current_owner_id());
CREATE FUNCTION app.reject_tool_action_payload_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
 IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
    OR NEW.request_id IS DISTINCT FROM OLD.request_id
    OR NEW.agent IS DISTINCT FROM OLD.agent
    OR NEW.tool_name IS DISTINCT FROM OLD.tool_name
    OR NEW.effect IS DISTINCT FROM OLD.effect
    OR NEW.arguments IS DISTINCT FROM OLD.arguments
    OR NEW.action_fingerprint IS DISTINCT FROM OLD.action_fingerprint
    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
   RAISE EXCEPTION 'tool action payload is immutable';
 END IF;
 RETURN NEW;
END; $$;
REVOKE ALL ON FUNCTION app.reject_tool_action_payload_update() FROM PUBLIC;
CREATE TRIGGER tool_action_payload_immutable
 BEFORE UPDATE ON app.tool_actions
 FOR EACH ROW EXECUTE FUNCTION app.reject_tool_action_payload_update();
"""


def upgrade():
    op.execute(DDL)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
