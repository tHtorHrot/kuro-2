"""Durable calendar drafts/jobs and independent completion deliveries; preserve old actions."""

from alembic import op

revision = "0009_calendar_tasks"
down_revision = "0008_executor_binding"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.assistant_requests DROP CONSTRAINT assistant_requests_status_check;
    ALTER TABLE app.assistant_requests ADD CONSTRAINT assistant_requests_status_check
      CHECK (status IN ('queued','preparing','awaiting_approval','approved','dispatching',
        'succeeded','failed','uncertain','cancelled','clarified','handed_off'));
    -- Keep ix_one_assistant_request: LLM calls still have one active turn per owner.
    ALTER TABLE app.tool_actions
      ADD COLUMN fingerprint_version integer NOT NULL DEFAULT 1
        CHECK (fingerprint_version IN (1,2)),
      ADD COLUMN latest_dispatch_at timestamptz,
      ADD CONSTRAINT tool_dispatch_window CHECK
        (latest_dispatch_at IS NULL OR latest_dispatch_at > due_at),
      ADD CONSTRAINT tool_schedule_binding CHECK
        (fingerprint_version = 1 OR latest_dispatch_at IS NOT NULL);
    ALTER TABLE app.external_identities ADD CONSTRAINT identity_owner_id UNIQUE(owner_id,id);
    CREATE TABLE app.calendar_tasks (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      bot_id bigint NOT NULL,
      chat_id bigint NOT NULL CHECK (chat_id > 0),
      identity_id uuid NOT NULL,
      conversation_id uuid NOT NULL,
      source_request_id uuid NOT NULL,
      state_revision integer NOT NULL CHECK (state_revision > 0),
      config_hash varchar(64) NOT NULL,
      grant_revision integer NOT NULL CHECK (grant_revision > 0),
      revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
      channel varchar(16) NOT NULL CHECK (channel='telegram'),
      anchor_at timestamptz NOT NULL,
      timezone varchar(64) NOT NULL,
      slots jsonb NOT NULL CHECK (octet_length(slots::text)<=12000),
      provenance jsonb NOT NULL CHECK (octet_length(provenance::text)<=24000),
      status varchar(24) NOT NULL CHECK
        (status IN ('draft','submitted','succeeded','failed','cancelled','uncertain','expired')),
      current_action_id uuid,
      expires_at timestamptz NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(owner_id,id),
      FOREIGN KEY(owner_id,identity_id) REFERENCES app.external_identities(owner_id,id),
      FOREIGN KEY(owner_id,source_request_id) REFERENCES app.assistant_requests(owner_id,id),
      FOREIGN KEY(owner_id,current_action_id) REFERENCES app.tool_actions(owner_id,id),
      FOREIGN KEY(owner_id,bot_id) REFERENCES app.telegram_state(owner_id,bot_id)
    );
    CREATE INDEX ix_calendar_drafts ON app.calendar_tasks(owner_id,conversation_id,status);
    CREATE TABLE app.calendar_notifications (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      bot_id bigint NOT NULL,
      chat_id bigint NOT NULL,
      task_id uuid NOT NULL,
      action_id uuid NOT NULL,
      event_key varchar(100) NOT NULL,
      reply_text text CHECK (octet_length(reply_text)<=16000),
      delivery_status varchar(16) NOT NULL CHECK
        (delivery_status IN ('pending','sending','sent','uncertain','failed','blocked','expired')),
      attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
      next_attempt_at timestamptz NOT NULL,
      telegram_message_id bigint,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(owner_id,event_key),
      FOREIGN KEY(owner_id,bot_id) REFERENCES app.telegram_state(owner_id,bot_id),
      FOREIGN KEY(owner_id,task_id) REFERENCES app.calendar_tasks(owner_id,id),
      FOREIGN KEY(owner_id,action_id) REFERENCES app.tool_actions(owner_id,id)
    );
    CREATE INDEX ix_calendar_notification_pending
      ON app.calendar_notifications(owner_id,bot_id,delivery_status,next_attempt_at);
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
        OR NEW.fingerprint_version IS DISTINCT FROM OLD.fingerprint_version
        OR NEW.latest_dispatch_at IS DISTINCT FROM OLD.latest_dispatch_at
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
    for table in ("calendar_tasks", "calendar_notifications"):
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON app.{table} TO jarvis_app")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_isolation ON app.{table} "
            "USING (owner_id=app.current_owner_id()) "
            "WITH CHECK (owner_id=app.current_owner_id())"
        )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; use verified restore or roll forward")
