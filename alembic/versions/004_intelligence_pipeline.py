"""Intelligence pipeline tables: l0_chunks, pipeline_traces, integrator_runs

Revision ID: 004
Revises: 003
Create Date: 2026-04-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --------------------------------------------------------------------------
    # 1. CREATE TABLE l0_chunks
    # --------------------------------------------------------------------------
    op.create_table(
        "l0_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_total", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("domain_scores", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("primary_domain", sa.Text(), nullable=True),
        sa.Column("is_crystal", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("classification_model", sa.Text(), nullable=True),
        sa.Column("classification_verified", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("verification_changed", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("processing_stage", sa.Text(), nullable=False, server_default=sa.text("'classified'")),
        sa.Column("error_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extraction_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_l0_chunks_ws_id"),
        sa.UniqueConstraint("workspace_id", "event_id", "chunk_index", name="uq_l0_chunks_ws_event_idx"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["l0_events.workspace_id", "l0_events.id"],
            name="fk_chunk_event",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "extraction_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_chunk_run",
        ),
    )

    op.execute(
        "CREATE INDEX idx_chunks_crystal ON l0_chunks (workspace_id, is_crystal, processing_stage) "
        "WHERE processing_stage = 'classified'"
    )
    op.execute("CREATE INDEX idx_chunks_event ON l0_chunks (workspace_id, event_id)")

    op.execute("ALTER TABLE l0_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE l0_chunks FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY chunks_workspace ON l0_chunks "
        "USING (workspace_id = current_setting('app.workspace_id', true)::uuid)"
    )

    # --------------------------------------------------------------------------
    # 2. CREATE TABLE pipeline_traces
    # --------------------------------------------------------------------------
    op.create_table(
        "pipeline_traces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", JSONB, nullable=True, server_default=sa.text("'{}'")),
        sa.Column("tokens_used", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Float(), nullable=True, server_default=sa.text("0.0")),
        sa.Column("duration_ms", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_pipeline_traces_ws_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["l0_events.workspace_id", "l0_events.id"],
            name="fk_trace_event",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "extraction_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_trace_run",
        ),
    )

    op.execute("CREATE INDEX idx_trace_event ON pipeline_traces (event_id, created_at)")

    op.execute("ALTER TABLE pipeline_traces ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pipeline_traces FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY traces_workspace ON pipeline_traces "
        "USING (workspace_id = current_setting('app.workspace_id', true)::uuid)"
    )

    # --------------------------------------------------------------------------
    # 3. CREATE TABLE integrator_runs
    # --------------------------------------------------------------------------
    op.create_table(
        "integrator_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("scope_description", sa.Text(), nullable=True),
        sa.Column("entities_scanned", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("entities_deduplicated", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("entities_enriched", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("relations_created", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("claims_updated", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("noise_removed", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Float(), nullable=True, server_default=sa.text("0.0")),
        sa.Column("duration_ms", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=True, server_default=sa.text("'running'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "id", name="uq_integrator_runs_ws_id"),
    )

    op.execute("ALTER TABLE integrator_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE integrator_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY integrator_runs_workspace ON integrator_runs "
        "USING (workspace_id = current_setting('app.workspace_id', true)::uuid)"
    )

    # --------------------------------------------------------------------------
    # 4. ALTER TABLE extraction_runs — add Cortex counter columns
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS chunks_total INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS chunks_crystal INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS chunks_skipped INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS cortex_cost_usd FLOAT NOT NULL DEFAULT 0.0")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS crystallizer_cost_usd FLOAT NOT NULL DEFAULT 0.0")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS verification_changes INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    # --------------------------------------------------------------------------
    # Remove extraction_runs columns
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS verification_changes")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS crystallizer_cost_usd")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS cortex_cost_usd")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS chunks_skipped")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS chunks_crystal")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS chunks_total")

    # --------------------------------------------------------------------------
    # Drop integrator_runs
    # --------------------------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS integrator_runs_workspace ON integrator_runs")
    op.execute("ALTER TABLE integrator_runs DISABLE ROW LEVEL SECURITY")
    op.drop_table("integrator_runs")

    # --------------------------------------------------------------------------
    # Drop pipeline_traces
    # --------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_trace_event")
    op.execute("DROP POLICY IF EXISTS traces_workspace ON pipeline_traces")
    op.execute("ALTER TABLE pipeline_traces DISABLE ROW LEVEL SECURITY")
    op.drop_table("pipeline_traces")

    # --------------------------------------------------------------------------
    # Drop l0_chunks
    # --------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_chunks_event")
    op.execute("DROP INDEX IF EXISTS idx_chunks_crystal")
    op.execute("DROP POLICY IF EXISTS chunks_workspace ON l0_chunks")
    op.execute("ALTER TABLE l0_chunks DISABLE ROW LEVEL SECURITY")
    op.drop_table("l0_chunks")
