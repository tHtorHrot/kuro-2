"""Durable private Telegram transport; no incoming content is persisted."""

from alembic import op

revision = "0002_telegram"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE app.telegram_state (
  owner_id uuid PRIMARY KEY REFERENCES app.users(id),
  bot_id bigint NOT NULL CHECK (bot_id>0),
  next_offset bigint CHECK (next_offset>=0),
  last_update_at timestamptz,
  last_poll_at timestamptz,
  send_not_before timestamptz,
  rate_window_at timestamptz NOT NULL,
  rate_count integer NOT NULL DEFAULT 0 CHECK (rate_count BETWEEN 0 AND 20),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT telegram_bot_owner UNIQUE(bot_id),
  CONSTRAINT telegram_owner_bot UNIQUE(owner_id,bot_id)
);
CREATE TABLE app.telegram_receipts (
  owner_id uuid NOT NULL,
  bot_id bigint NOT NULL,
  update_id bigint NOT NULL CHECK (update_id>=0),
  chat_id bigint NOT NULL CHECK (chat_id>0),
  reply_kind varchar(32) CHECK (reply_kind IN
    ('unpaired','paired','pair_failed','already_paired','help','status','privacy','unsupported')),
  requires_pairing boolean NOT NULL DEFAULT true,
  delivery_status varchar(16) NOT NULL CHECK (delivery_status IN
    ('pending','sending','sent','uncertain','failed','blocked','ignored','expired')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
  next_attempt_at timestamptz NOT NULL,
  telegram_message_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(owner_id,bot_id,update_id),
  FOREIGN KEY(owner_id,bot_id) REFERENCES app.telegram_state(owner_id,bot_id)
);
CREATE INDEX ix_telegram_delivery ON app.telegram_receipts(owner_id,bot_id,next_attempt_at)
  WHERE delivery_status='pending';
CREATE INDEX ix_telegram_retention ON app.telegram_receipts(owner_id,bot_id,created_at);
REVOKE ALL ON app.telegram_state, app.telegram_receipts FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON app.telegram_state TO jarvis_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON app.telegram_receipts TO jarvis_app;
"""


def upgrade():
    op.execute(DDL)
    for table in ("telegram_state", "telegram_receipts"):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_isolation ON app.{table} "
            "USING (owner_id = app.current_owner_id()) "
            "WITH CHECK (owner_id = app.current_owner_id())"
        )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
