"""Stage 6 slice 3 — registered projects and per-project memory scoping.

New: app.projects registry (owner-scoped names) and app.project_state holding
the owner's active project. app.profile_memory gains a nullable project tag;
NULL means global (visible in every project). Deleting a project that still
owns facts or is active is rejected; forget the facts or switch away first.
RLS owner isolation on all new tables; additive, forward-only.
"""

from alembic import op

revision = "0016_memory_projects"
down_revision = "0015_memory_kinds"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.projects (
      owner_id uuid NOT NULL REFERENCES app.users(id),
      name varchar(40) NOT NULL CHECK (name ~ '^[a-z][a-z0-9_-]{0,39}$'),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (owner_id, name)
    );
    CREATE TABLE app.project_state (
      owner_id uuid NOT NULL PRIMARY KEY REFERENCES app.users(id),
      active_project varchar(40),
      updated_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (owner_id, active_project) REFERENCES app.projects(owner_id, name)
    );
    ALTER TABLE app.profile_memory
      ADD COLUMN project varchar(40),
      ADD CONSTRAINT profile_memory_project_fk
        FOREIGN KEY (owner_id, project) REFERENCES app.projects(owner_id, name);
    CREATE INDEX ix_profile_memory_project
      ON app.profile_memory(owner_id, project, status);
    """)
    for table in ("projects", "project_state"):
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON app.{table} TO jarvis_app")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_isolation ON app.{table} "
            "USING (owner_id=app.current_owner_id()) "
            "WITH CHECK (owner_id=app.current_owner_id())"
        )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup or roll forward")
