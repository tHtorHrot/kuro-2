"""Stage 7 slice Documents — izinkan role documents pada tasks.

Additive, forward-only: lepas CHECK lama, pasang ulang plus 'documents'.
Migrasi 0001–0016 tidak diubah.
"""

from alembic import op

revision = "0017_task_role_documents"
down_revision = "0016_memory_projects"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE app.tasks DROP CONSTRAINT tasks_role_check")
    op.execute("""
    ALTER TABLE app.tasks ADD CONSTRAINT tasks_role_check CHECK (
      role IN ('research','coding','knowledge','data','communication','planner','documents')
    );
    """)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
