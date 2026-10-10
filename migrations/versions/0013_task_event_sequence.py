"""KURO Ultimate fix — USAGE grant untuk task_events_id_seq.

0010 membuat app.task_events.id sebagai bigserial tetapi hanya memberi
SELECT/INSERT/UPDATE pada tabel. Role jarvis_app juga butuh USAGE pada
sequence, jika tidak INSERT event gagal dengan InsufficientPrivilege dan
worker Telegram crash-loop pada update /goal pertama. Additive, forward-only.
"""

from alembic import op

revision = "0013_task_event_sequence"
down_revision = "0012_task_reliability"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("GRANT USAGE, SELECT ON SEQUENCE app.task_events_id_seq TO jarvis_app")


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
