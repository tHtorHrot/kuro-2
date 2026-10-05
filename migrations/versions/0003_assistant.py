"""Owner-private memory, durable AI journal and per-attempt authorization ledger."""

from alembic import op

revision = "0003_assistant"
down_revision = "0002_telegram"
branch_labels = None
depends_on = None

DDL = """
ALTER TABLE app.telegram_receipts ADD COLUMN reply_text text
  CHECK (octet_length(reply_text)<=16000);
ALTER TABLE app.telegram_receipts DROP CONSTRAINT telegram_receipts_reply_kind_check;
ALTER TABLE app.telegram_receipts ADD CONSTRAINT telegram_receipts_reply_kind_check
 CHECK (reply_kind IN ('unpaired','paired','pair_failed','already_paired','help','status',
 'privacy','unsupported','assistant'));
ALTER TABLE app.telegram_receipts DROP CONSTRAINT telegram_receipts_delivery_status_check;
ALTER TABLE app.telegram_receipts ADD CONSTRAINT telegram_receipts_delivery_status_check
 CHECK (delivery_status IN ('pending','sending','sent','uncertain','failed','blocked',
 'ignored','expired','waiting'));
CREATE TABLE app.assistant_state (
 owner_id uuid PRIMARY KEY REFERENCES app.users(id),
 enabled boolean NOT NULL DEFAULT false,
 frozen boolean NOT NULL DEFAULT false,
 revision integer NOT NULL DEFAULT 1 CHECK (revision>0),
 conversation_id uuid NOT NULL,
 config_hash varchar(64) NOT NULL,
 last_poll_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app.profile_memory (
 owner_id uuid NOT NULL REFERENCES app.users(id),
 key varchar(40) NOT NULL,
 value text NOT NULL CHECK (octet_length(value)<=4000),
 data_class varchar(16) NOT NULL DEFAULT 'private' CHECK (data_class IN ('private','restricted')),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (owner_id,key)
);
CREATE TABLE app.assistant_requests (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL REFERENCES app.users(id),
 bot_id bigint NOT NULL,
 source_update_id bigint NOT NULL,
 reply_update_id bigint NOT NULL,
 conversation_id uuid NOT NULL,
 revision integer NOT NULL,
 config_hash varchar(64) NOT NULL,
 prompt text CHECK (octet_length(prompt)<=16000),
 messages jsonb,
 context_hash varchar(64),
 data_class varchar(16) NOT NULL DEFAULT 'private' CHECK (data_class IN ('private','restricted')),
 status varchar(24) NOT NULL CHECK (status IN ('queued','preparing','awaiting_approval',
  'approved','dispatching','succeeded','failed','uncertain','cancelled')),
 plan jsonb,
 approval_digest bytea CHECK (octet_length(approval_digest)=32),
 approval_expires_at timestamptz,
 approved_at timestamptz,
 consumed_at timestamptz,
 approval_attempts integer NOT NULL DEFAULT 0 CHECK (approval_attempts BETWEEN 0 AND 5),
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 UNIQUE(owner_id,id), UNIQUE(owner_id,bot_id,source_update_id),
 FOREIGN KEY(owner_id,bot_id) REFERENCES app.telegram_state(owner_id,bot_id)
);
CREATE UNIQUE INDEX ix_one_assistant_request ON app.assistant_requests(owner_id)
 WHERE status IN ('queued','preparing','awaiting_approval','approved','dispatching');
CREATE INDEX ix_assistant_request_retention ON app.assistant_requests(owner_id,created_at);
CREATE TABLE app.conversation_messages (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL REFERENCES app.users(id),
 conversation_id uuid NOT NULL,
 request_id uuid NOT NULL,
 role varchar(12) NOT NULL CHECK (role IN ('user','assistant')),
 content text NOT NULL CHECK (octet_length(content)<=16000),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(owner_id,request_id) REFERENCES app.assistant_requests(owner_id,id),
 UNIQUE(owner_id,request_id,role)
);
CREATE INDEX ix_conversation_recent
 ON app.conversation_messages(owner_id,conversation_id,created_at);
CREATE TABLE app.llm_calls (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL REFERENCES app.users(id),
 request_id uuid NOT NULL,
 kind varchar(12) NOT NULL CHECK (kind IN ('free','premium')),
 model varchar(200) NOT NULL,
 provider varchar(120) NOT NULL,
 status varchar(16) NOT NULL CHECK (status IN ('dispatching','succeeded','rejected','uncertain')),
 reserved_usd numeric(20,10) NOT NULL CHECK (reserved_usd>=0),
 actual_usd numeric(20,10) CHECK (actual_usd>=0),
 prompt_tokens integer CHECK (prompt_tokens>=0),
 completion_tokens integer CHECK (completion_tokens>=0),
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 FOREIGN KEY(owner_id,request_id) REFERENCES app.assistant_requests(owner_id,id),
 UNIQUE(owner_id,request_id,kind)
);
CREATE INDEX ix_llm_budget ON app.llm_calls(owner_id,created_at);
"""


def upgrade():
    op.execute(DDL)
    for table in (
        "assistant_state",
        "profile_memory",
        "assistant_requests",
        "conversation_messages",
        "llm_calls",
    ):
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC")
        privileges = "SELECT,INSERT,UPDATE"
        if table in {"profile_memory", "conversation_messages"}:
            privileges += ",DELETE"
        op.execute(f"GRANT {privileges} ON app.{table} TO jarvis_app")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_isolation ON app.{table} "
            "USING (owner_id=app.current_owner_id()) "
            "WITH CHECK (owner_id=app.current_owner_id())"
        )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
