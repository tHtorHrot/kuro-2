"""Retention grant — DELETE khusus untuk task event log turunan.

task_events adalah data turunan (progress), bukan journal otoritatif;
retention batch membutuhkannya. Tasks, runs, artifacts, journal, dan semua
tabel lain tetap tanpa DELETE untuk role aplikasi. RLS owner isolation
tetap berlaku. Additive, forward-only.
"""

from alembic import op

revision = "0014_task_event_retention"
down_revision = "0013_task_event_sequence"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("GRANT DELETE ON TABLE app.task_events TO jarvis_app")


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
