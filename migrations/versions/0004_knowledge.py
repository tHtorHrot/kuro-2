"""Owner-scoped document queue and immutable retrieval snapshots."""

from alembic import op

revision = "0004_knowledge"
down_revision = "0003_assistant"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE app.knowledge_state (
 owner_id uuid PRIMARY KEY REFERENCES app.users(id), last_poll_at timestamptz
);
CREATE TABLE app.documents (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES app.users(id),
 title varchar(120) NOT NULL,
 kind varchar(8) NOT NULL CHECK (kind IN ('pdf','docx','png','jpg','jpeg')),
 data_class varchar(16) NOT NULL CHECK (data_class IN ('private','restricted')),
 sha256 varchar(64), pipeline varchar(64) NOT NULL,
 ocr varchar(8) NOT NULL CHECK (ocr IN ('auto','always','never')),
 status varchar(16) NOT NULL CHECK
   (status IN ('queued','processing','ready','failed','deleting','deleted')),
 byte_size bigint NOT NULL CHECK (byte_size BETWEEN 0 AND 20971520),
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
 lease_until timestamptz, lease_token uuid, error_code varchar(80),
 chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count BETWEEN 0 AND 1500),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(owner_id,id)
);
CREATE UNIQUE INDEX ix_document_hash ON app.documents(owner_id,sha256,pipeline)
 WHERE status <> 'deleted';
CREATE INDEX ix_document_queue ON app.documents(owner_id,status,lease_until);
CREATE TABLE app.document_chunks (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES app.users(id),
 document_id uuid NOT NULL, ordinal integer NOT NULL CHECK (ordinal BETWEEN 0 AND 1499),
 locator varchar(120) NOT NULL, content text NOT NULL CHECK (octet_length(content)<=4800),
 UNIQUE(owner_id,document_id,ordinal),
 FOREIGN KEY(owner_id,document_id) REFERENCES app.documents(owner_id,id)
);
ALTER TABLE app.assistant_requests ADD COLUMN document_id uuid;
ALTER TABLE app.assistant_requests ADD COLUMN document_sources jsonb
 CHECK (octet_length(document_sources::text)<=65536);
ALTER TABLE app.assistant_requests ADD CONSTRAINT request_document_owner
 FOREIGN KEY(owner_id,document_id) REFERENCES app.documents(owner_id,id);
CREATE INDEX ix_request_document ON app.assistant_requests(owner_id,document_id);
ALTER TABLE app.telegram_receipts DROP CONSTRAINT telegram_receipts_reply_kind_check;
ALTER TABLE app.telegram_receipts ADD CONSTRAINT telegram_receipts_reply_kind_check
 CHECK (reply_kind IN ('unpaired','paired','pair_failed','already_paired','help','status',
 'privacy','unsupported','assistant','knowledge'));
"""


def upgrade():
    op.execute(DDL)
    for table in ("knowledge_state", "documents", "document_chunks"):
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC")
        grants = "SELECT,INSERT,UPDATE" + (",DELETE" if table == "document_chunks" else "")
        op.execute(f"GRANT {grants} ON app.{table} TO jarvis_app")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_isolation ON app.{table} "
            "USING (owner_id=app.current_owner_id()) "
            "WITH CHECK (owner_id=app.current_owner_id())"
        )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
