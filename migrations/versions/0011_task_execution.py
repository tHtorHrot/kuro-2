"""KURO Ultimate Phase 2 — task execution linkage.

Additive: task_run_id nullable pada tool_actions dan llm_calls.
Existing Calendar actions tetap valid tanpa field baru.
Constraint LLM: call milik chat request ATAU task run (jangan fake request).
"""

from alembic import op

revision = "0011_task_execution"
down_revision = "0010_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.tool_actions ADD COLUMN task_run_id uuid;
    ALTER TABLE app.tool_actions
      ADD CONSTRAINT tool_action_task_run_fk
      FOREIGN KEY(owner_id, task_run_id) REFERENCES app.task_runs(owner_id, id)
      DEFERRABLE INITIALLY DEFERRED;
    CREATE INDEX ix_tool_actions_run ON app.tool_actions(owner_id, task_run_id)
      WHERE task_run_id IS NOT NULL;

    ALTER TABLE app.llm_calls ADD COLUMN task_run_id uuid;
    ALTER TABLE app.llm_calls ALTER COLUMN request_id DROP NOT NULL;
    ALTER TABLE app.llm_calls
      ADD CONSTRAINT llm_call_task_run_fk
      FOREIGN KEY(owner_id, task_run_id) REFERENCES app.task_runs(owner_id, id)
      DEFERRABLE INITIALLY DEFERRED;
    ALTER TABLE app.llm_calls
      ADD CONSTRAINT llm_call_owner_check
      CHECK (request_id IS NOT NULL OR task_run_id IS NOT NULL);
    CREATE INDEX ix_llm_calls_run ON app.llm_calls(owner_id, task_run_id)
      WHERE task_run_id IS NOT NULL;
    """)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
