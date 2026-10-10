"""KURO Ultimate Phase 3/4 — reliability indexes + recurring automation (opsional).

Additive. Automation definition/run terpisah (idempotency occurrence +
timezone); tidak menggandakan occurrence saat restart. Retention event
dilakukan batch; jangan full-table delete setiap startup.
"""

from alembic import op

revision = "0012_task_reliability"
down_revision = "0011_task_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE INDEX IF NOT EXISTS ix_tasks_deadline
      ON app.tasks(owner_id, deadline_at) WHERE status NOT IN ('succeeded','failed','cancelled');
    CREATE INDEX IF NOT EXISTS ix_task_events_retention
      ON app.task_events(owner_id, created_at);

    CREATE TABLE app.automation_definitions (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      title varchar(120) NOT NULL,
      timezone varchar(64) NOT NULL DEFAULT 'UTC',
      rrule varchar(256) NOT NULL,
      goal_template text NOT NULL CHECK (octet_length(goal_template) <= 8000),
      enabled boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(owner_id, id)
    );
    CREATE TABLE app.automation_runs (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      definition_id uuid NOT NULL,
      occurrence_at timestamptz NOT NULL,
      occurrence_key varchar(128) NOT NULL,
      task_id uuid,
      status varchar(16) NOT NULL DEFAULT 'launched'
        CHECK (status IN ('launched','adopted','failed','skipped')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(owner_id, occurrence_key),
      FOREIGN KEY(owner_id, definition_id)
        REFERENCES app.automation_definitions(owner_id, id) ON DELETE CASCADE
    );
    CREATE INDEX ix_automation_runs_def
      ON app.automation_runs(owner_id, definition_id, occurrence_at);
    """)
    for table in ("automation_definitions", "automation_runs"):
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
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
