"""Bind grants to Calendar credentials and persist scheduler health."""

from alembic import op

revision = "0008_executor_binding"
down_revision = "0007_action_authority"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.tool_grants
      ADD COLUMN binding_fingerprint varchar(64),
      ADD COLUMN last_poll_at timestamptz,
      ADD CONSTRAINT tool_grant_binding_format CHECK
        (binding_fingerprint IS NULL OR binding_fingerprint ~ '^[0-9a-f]{64}$');
    """)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
