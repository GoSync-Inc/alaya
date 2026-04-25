"""Granular token columns on pipeline_traces, extraction_runs, integrator_runs.

Revision ID: 009
Revises: 008
Create Date: 2026-04-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --------------------------------------------------------------------------
    # 1. ALTER TABLE pipeline_traces — add 5 new token-class columns
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE pipeline_traces ADD COLUMN tokens_in INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE pipeline_traces ADD COLUMN tokens_out INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE pipeline_traces ADD COLUMN tokens_cached INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE pipeline_traces ADD COLUMN cache_write_5m_tokens INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE pipeline_traces ADD COLUMN cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0")

    # 2. Add integrator_run_id column (nullable, no FK yet)
    op.execute("ALTER TABLE pipeline_traces ADD COLUMN integrator_run_id UUID")

    # 3. Drop NOT NULL on event_id — traces can be scoped to integrator runs
    op.execute("ALTER TABLE pipeline_traces ALTER COLUMN event_id DROP NOT NULL")

    # 4. Add composite FK from (workspace_id, integrator_run_id) to integrator_runs(workspace_id, id)
    op.execute(
        "ALTER TABLE pipeline_traces"
        " ADD CONSTRAINT fk_trace_integrator_run"
        " FOREIGN KEY (workspace_id, integrator_run_id)"
        " REFERENCES integrator_runs(workspace_id, id)"
    )

    # 5. Add CHECK: at least one parent scope must be non-NULL
    op.execute(
        "ALTER TABLE pipeline_traces"
        " ADD CONSTRAINT ck_trace_has_parent_scope CHECK ("
        "  event_id IS NOT NULL"
        "  OR extraction_run_id IS NOT NULL"
        "  OR integrator_run_id IS NOT NULL"
        ")"
    )

    # 6. Partial index on integrator_run_id for efficient trace lookups
    op.execute(
        "CREATE INDEX idx_pipeline_traces_integrator_run_id"
        " ON pipeline_traces(integrator_run_id)"
        " WHERE integrator_run_id IS NOT NULL"
    )

    # --------------------------------------------------------------------------
    # 7. ALTER TABLE extraction_runs — add 2 cache-write columns (the other token
    #    columns already exist from migrations 003+004)
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE extraction_runs ADD COLUMN cache_write_5m_tokens INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0")

    # --------------------------------------------------------------------------
    # 8. ALTER TABLE integrator_runs — add 5 granular token-class columns
    #    (integrator_runs currently only has tokens_used, cost_usd, duration_ms)
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE integrator_runs ADD COLUMN tokens_in INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE integrator_runs ADD COLUMN tokens_out INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE integrator_runs ADD COLUMN tokens_cached INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE integrator_runs ADD COLUMN cache_write_5m_tokens INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE integrator_runs ADD COLUMN cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    # Safety check: abort if any pipeline_traces rows have NULL event_id.
    # Those are integrator-scoped traces — drop them manually before downgrading.
    from sqlalchemy import text

    from alembic import op as alembic_op

    conn = alembic_op.get_bind()
    result = conn.execute(text("SELECT COUNT(*) FROM pipeline_traces WHERE event_id IS NULL"))
    null_count = result.scalar()
    if null_count and null_count > 0:
        raise RuntimeError(
            f"Cannot downgrade: {null_count} pipeline_traces rows have NULL event_id "
            "(integrator-scoped traces). Delete them first:\n"
            "  DELETE FROM pipeline_traces WHERE event_id IS NULL;\n"
            "Then re-run the downgrade."
        )

    # Undo integrator_runs columns
    op.execute("ALTER TABLE integrator_runs DROP COLUMN IF EXISTS cache_write_1h_tokens")
    op.execute("ALTER TABLE integrator_runs DROP COLUMN IF EXISTS cache_write_5m_tokens")
    op.execute("ALTER TABLE integrator_runs DROP COLUMN IF EXISTS tokens_cached")
    op.execute("ALTER TABLE integrator_runs DROP COLUMN IF EXISTS tokens_out")
    op.execute("ALTER TABLE integrator_runs DROP COLUMN IF EXISTS tokens_in")

    # Undo extraction_runs columns
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS cache_write_1h_tokens")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS cache_write_5m_tokens")

    # Undo pipeline_traces: index, constraint, FK, columns, NOT NULL
    op.execute("DROP INDEX IF EXISTS idx_pipeline_traces_integrator_run_id")
    op.execute("ALTER TABLE pipeline_traces DROP CONSTRAINT IF EXISTS ck_trace_has_parent_scope")
    op.execute("ALTER TABLE pipeline_traces DROP CONSTRAINT IF EXISTS fk_trace_integrator_run")
    op.execute("ALTER TABLE pipeline_traces DROP COLUMN IF EXISTS integrator_run_id")
    op.execute("ALTER TABLE pipeline_traces DROP COLUMN IF EXISTS cache_write_1h_tokens")
    op.execute("ALTER TABLE pipeline_traces DROP COLUMN IF EXISTS cache_write_5m_tokens")
    op.execute("ALTER TABLE pipeline_traces DROP COLUMN IF EXISTS tokens_cached")
    op.execute("ALTER TABLE pipeline_traces DROP COLUMN IF EXISTS tokens_out")
    op.execute("ALTER TABLE pipeline_traces DROP COLUMN IF EXISTS tokens_in")

    # Restore NOT NULL on event_id (safe: we verified above that no NULLs exist)
    op.execute("ALTER TABLE pipeline_traces ALTER COLUMN event_id SET NOT NULL")
