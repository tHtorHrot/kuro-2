"""KURO Ultimate Phase 1 — durable Task/Run model dan idempotent admission.

Additive; tidak mengubah semantik action Calendar existing.
Lima tabel baru: tasks, task_dependencies, task_runs, artifacts, task_events.
"""

from alembic import op

revision = "0010_tasks"
down_revision = "0009_calendar_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.tasks (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      parent_id uuid,
      root_id uuid,
      client_request_key varchar(128),
      payload_hash varchar(64),
      title varchar(120) NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
      goal text CHECK (octet_length(goal) <= 16000),
      role varchar(32) NOT NULL DEFAULT 'research'
        CHECK (role IN ('research','coding','knowledge','data','communication','planner')),
      input_refs jsonb,
      acceptance jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (octet_length(acceptance::text) <= 8000),
      plan_json jsonb CHECK (octet_length(plan_json::text) <= 64000),
      plan_revision integer NOT NULL DEFAULT 1 CHECK (plan_revision > 0),
      status varchar(24) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('draft','queued','running','waiting_approval',
          'waiting_dependency','succeeded','failed','uncertain','cancelled')),
      priority integer NOT NULL DEFAULT 0 CHECK (priority BETWEEN -100 AND 100),
      not_before timestamptz,
      deadline_at timestamptz,
      cost_ceiling_usd numeric(20,10) NOT NULL DEFAULT 1 CHECK (cost_ceiling_usd >= 0),
      cost_spent_usd numeric(20,10) NOT NULL DEFAULT 0 CHECK (cost_spent_usd >= 0),
      repair_passes integer NOT NULL DEFAULT 0 CHECK (repair_passes BETWEEN 0 AND 3),
      error_code varchar(80),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(owner_id, id)
    );
    CREATE UNIQUE INDEX ix_tasks_idempotent
      ON app.tasks(owner_id, client_request_key, payload_hash)
      WHERE client_request_key IS NOT NULL;
    CREATE INDEX ix_tasks_queue
      ON app.tasks(owner_id, status, priority DESC, not_before)
      WHERE status IN ('queued','waiting_dependency');
    CREATE INDEX ix_tasks_root ON app.tasks(owner_id, root_id, status);

    CREATE TABLE app.task_dependencies (
      owner_id uuid NOT NULL REFERENCES app.users(id),
      task_id uuid NOT NULL,
      depends_on_id uuid NOT NULL,
      PRIMARY KEY (owner_id, task_id, depends_on_id),
      CHECK (task_id != depends_on_id),
      FOREIGN KEY(owner_id, task_id) REFERENCES app.tasks(owner_id, id) ON DELETE CASCADE,
      FOREIGN KEY(owner_id, depends_on_id) REFERENCES app.tasks(owner_id, id) ON DELETE CASCADE
    );

    CREATE TABLE app.task_runs (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      task_id uuid NOT NULL,
      attempt integer NOT NULL DEFAULT 1 CHECK (attempt BETWEEN 1 AND 10),
      worker_instance varchar(80) NOT NULL DEFAULT 'inline',
      generation integer NOT NULL DEFAULT 1 CHECK (generation > 0),
      lease_token uuid,
      lease_expires_at timestamptz,
      heartbeat_at timestamptz,
      status varchar(16) NOT NULL DEFAULT 'claimed'
        CHECK (status IN ('claimed','running','succeeded','failed','lost','cancelled','uncertain')),
      model_route varchar(120),
      reserved_usd numeric(20,10) NOT NULL DEFAULT 0 CHECK (reserved_usd >= 0),
      actual_usd numeric(20,10) CHECK (actual_usd IS NULL OR actual_usd >= 0),
      error_code varchar(80),
      provider_session_id varchar(128),
      created_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz,
      UNIQUE(owner_id, id),
      FOREIGN KEY(owner_id, task_id) REFERENCES app.tasks(owner_id, id) ON DELETE CASCADE
    );
    CREATE UNIQUE INDEX ix_one_active_run
      ON app.task_runs(owner_id, task_id)
      WHERE status IN ('claimed','running');
    CREATE INDEX ix_runs_lease ON app.task_runs(owner_id, lease_expires_at)
      WHERE status IN ('claimed','running');

    CREATE TABLE app.artifacts (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      task_id uuid NOT NULL,
      run_id uuid,
      rel_path varchar(256) NOT NULL CHECK (rel_path NOT LIKE '/%' AND rel_path NOT LIKE '%..%'),
      object_key varchar(512),
      sha256 varchar(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
      byte_size bigint NOT NULL DEFAULT 0 CHECK (byte_size BETWEEN 0 AND 20971520),
      media_type varchar(80) NOT NULL DEFAULT 'text/plain',
      data_class varchar(16) NOT NULL DEFAULT 'private'
        CHECK (data_class IN ('public','private','restricted')),
      evaluation_status varchar(16) NOT NULL DEFAULT 'pending'
        CHECK (evaluation_status IN ('pending','passed','failed','needs_human')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(owner_id, id),
      FOREIGN KEY(owner_id, task_id) REFERENCES app.tasks(owner_id, id) ON DELETE CASCADE
    );
    CREATE INDEX ix_artifacts_task ON app.artifacts(owner_id, task_id, created_at);

    CREATE TABLE app.task_events (
      id bigserial PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      task_id uuid,
      run_id uuid,
      event_type varchar(48) NOT NULL,
      payload jsonb CHECK (payload IS NULL OR octet_length(payload::text) <= 8000),
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_task_events_cursor ON app.task_events(owner_id, id);
    CREATE INDEX ix_task_events_task ON app.task_events(owner_id, task_id, id);
    """)
    for table in ("tasks", "task_dependencies", "task_runs", "artifacts", "task_events"):
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
