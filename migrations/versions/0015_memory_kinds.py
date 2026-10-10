"""Stage 6 slice 1 — typed memory: kind, provenance, expiry, validation status.

app.profile_memory gains owner-scoped kinds (profile/preference/project/
episodic/task), persisted provenance, optional expiry, and an explicit
validation status so forget becomes a tombstone instead of a hard delete.
Existing rows backfill to kind=profile/status=active with no expiry.
RLS, grants, and the (owner_id,key) identity are unchanged. Additive,
forward-only.
"""

from alembic import op

revision = "0015_memory_kinds"
down_revision = "0014_task_event_retention"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.profile_memory
      ADD COLUMN kind varchar(16) NOT NULL DEFAULT 'profile'
        CHECK (kind IN ('profile','preference','project','episodic','task')),
      ADD COLUMN provenance text,
      ADD COLUMN expires_at timestamptz,
      ADD COLUMN status varchar(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','superseded','deleted')),
      ADD COLUMN importance real NOT NULL DEFAULT 0.5
        CHECK (importance BETWEEN 0 AND 1),
      ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
    CREATE INDEX ix_profile_memory_kind
      ON app.profile_memory(owner_id, kind, status);
    """)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
