"""Extraction schema expansion

Revision ID: 003
Revises: 002
Create Date: 2026-04-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --------------------------------------------------------------------------
    # 1. CREATE TABLE extraction_runs (must come first — other tables FK to it)
    # --------------------------------------------------------------------------
    op.create_table(
        "extraction_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("llm_provider", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_cached", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0.0")),
        sa.Column("raw_extraction", JSONB, nullable=True),
        sa.Column("entities_created", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("entities_merged", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("relations_created", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("claims_created", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("claims_superseded", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("resolver_decisions", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_detail", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("parent_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_extraction_runs_ws_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["l0_events.workspace_id", "l0_events.id"],
            name="fk_extraction_run_event",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "parent_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_extraction_run_parent",
        ),
    )

    # --------------------------------------------------------------------------
    # 2. ALTER TABLE l0_events ADD COLUMNS
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE l0_events ADD COLUMN IF NOT EXISTS raw_text TEXT")
    op.execute("ALTER TABLE l0_events ADD COLUMN IF NOT EXISTS access_level TEXT NOT NULL DEFAULT 'public'")
    op.execute("ALTER TABLE l0_events ADD COLUMN IF NOT EXISTS access_context TEXT")
    op.execute("ALTER TABLE l0_events ADD COLUMN IF NOT EXISTS actor_external_id TEXT")
    op.execute("ALTER TABLE l0_events ADD COLUMN IF NOT EXISTS event_kind TEXT")
    op.execute("ALTER TABLE l0_events ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ")
    op.execute("ALTER TABLE l0_events ADD COLUMN IF NOT EXISTS is_extracted BOOLEAN NOT NULL DEFAULT FALSE")

    # --------------------------------------------------------------------------
    # 3. ALTER TABLE l1_entities ADD COLUMNS
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE l1_entities ADD COLUMN IF NOT EXISTS aliases TEXT[] DEFAULT '{}'")
    op.execute("ALTER TABLE l1_entities ADD COLUMN IF NOT EXISTS extraction_run_id UUID")
    op.execute(
        "ALTER TABLE l1_entities ADD CONSTRAINT fk_entity_extraction_run "
        "FOREIGN KEY (workspace_id, extraction_run_id) "
        "REFERENCES extraction_runs(workspace_id, id)"
    )

    # --------------------------------------------------------------------------
    # 4. ALTER TABLE l2_claims ADD COLUMNS
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE l2_claims ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE l2_claims ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE l2_claims ADD COLUMN IF NOT EXISTS supersedes UUID")
    op.execute(
        "ALTER TABLE l2_claims ADD CONSTRAINT fk_claim_supersedes "
        "FOREIGN KEY (workspace_id, supersedes) "
        "REFERENCES l2_claims(workspace_id, id)"
    )
    op.execute("ALTER TABLE l2_claims ADD COLUMN IF NOT EXISTS source_summary TEXT")
    op.execute("ALTER TABLE l2_claims ADD COLUMN IF NOT EXISTS value_type TEXT NOT NULL DEFAULT 'text'")
    op.execute("ALTER TABLE l2_claims ADD COLUMN IF NOT EXISTS extraction_run_id UUID")
    op.execute(
        "ALTER TABLE l2_claims ADD CONSTRAINT fk_claim_extraction_run "
        "FOREIGN KEY (workspace_id, extraction_run_id) "
        "REFERENCES extraction_runs(workspace_id, id)"
    )

    # --------------------------------------------------------------------------
    # 5. ALTER TABLE l1_relations ADD COLUMN
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE l1_relations ADD COLUMN IF NOT EXISTS extraction_run_id UUID")
    op.execute(
        "ALTER TABLE l1_relations ADD CONSTRAINT fk_relation_extraction_run "
        "FOREIGN KEY (workspace_id, extraction_run_id) "
        "REFERENCES extraction_runs(workspace_id, id)"
    )

    # --------------------------------------------------------------------------
    # 6. ALTER TABLE predicate_definitions ADD COLUMN
    # --------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE predicate_definitions ADD COLUMN IF NOT EXISTS "
        "supersession_strategy TEXT NOT NULL DEFAULT 'latest_wins'"
    )

    # --------------------------------------------------------------------------
    # 7. ADD UNIQUE INDEX on entity_external_ids
    # --------------------------------------------------------------------------
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_ids_ws_src_ext "
        "ON entity_external_ids(workspace_id, source_type, external_id)"
    )

    # --------------------------------------------------------------------------
    # 8. ADD INDEXES
    # --------------------------------------------------------------------------
    op.execute("CREATE INDEX IF NOT EXISTS idx_extraction_runs_ws ON extraction_runs(workspace_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_extraction_runs_event ON extraction_runs(event_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_l0_not_extracted ON l0_events(workspace_id) WHERE NOT is_extracted")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_l2_entity_predicate_active "
        "ON l2_claims(entity_id, predicate) WHERE status = 'active'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_l2_extraction_run ON l2_claims(extraction_run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rel_source ON l1_relations(source_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rel_target ON l1_relations(target_entity_id)")

    # --------------------------------------------------------------------------
    # 9. RLS on extraction_runs
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE extraction_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extraction_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON extraction_runs "
        "USING (workspace_id = current_setting('app.workspace_id', true)::uuid)"
    )


def downgrade() -> None:
    # --------------------------------------------------------------------------
    # Drop indexes
    # --------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_rel_target")
    op.execute("DROP INDEX IF EXISTS idx_rel_source")
    op.execute("DROP INDEX IF EXISTS idx_l2_extraction_run")
    op.execute("DROP INDEX IF EXISTS idx_l2_entity_predicate_active")
    op.execute("DROP INDEX IF EXISTS idx_l0_not_extracted")
    op.execute("DROP INDEX IF EXISTS idx_extraction_runs_event")
    op.execute("DROP INDEX IF EXISTS idx_extraction_runs_ws")
    op.execute("DROP INDEX IF EXISTS idx_ext_ids_ws_src_ext")

    # --------------------------------------------------------------------------
    # Drop RLS on extraction_runs
    # --------------------------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS workspace_isolation ON extraction_runs")
    op.execute("ALTER TABLE extraction_runs DISABLE ROW LEVEL SECURITY")

    # --------------------------------------------------------------------------
    # Drop FK constraints and columns from ALTER TABLE tables
    # --------------------------------------------------------------------------
    # predicate_definitions
    op.execute("ALTER TABLE predicate_definitions DROP COLUMN IF EXISTS supersession_strategy")

    # l1_relations
    op.execute("ALTER TABLE l1_relations DROP CONSTRAINT IF EXISTS fk_relation_extraction_run")
    op.execute("ALTER TABLE l1_relations DROP COLUMN IF EXISTS extraction_run_id")

    # l2_claims
    op.execute("ALTER TABLE l2_claims DROP CONSTRAINT IF EXISTS fk_claim_extraction_run")
    op.execute("ALTER TABLE l2_claims DROP CONSTRAINT IF EXISTS fk_claim_supersedes")
    op.execute("ALTER TABLE l2_claims DROP COLUMN IF EXISTS extraction_run_id")
    op.execute("ALTER TABLE l2_claims DROP COLUMN IF EXISTS value_type")
    op.execute("ALTER TABLE l2_claims DROP COLUMN IF EXISTS source_summary")
    op.execute("ALTER TABLE l2_claims DROP COLUMN IF EXISTS supersedes")
    op.execute("ALTER TABLE l2_claims DROP COLUMN IF EXISTS observed_at")
    op.execute("ALTER TABLE l2_claims DROP COLUMN IF EXISTS status")

    # l1_entities
    op.execute("ALTER TABLE l1_entities DROP CONSTRAINT IF EXISTS fk_entity_extraction_run")
    op.execute("ALTER TABLE l1_entities DROP COLUMN IF EXISTS extraction_run_id")
    op.execute("ALTER TABLE l1_entities DROP COLUMN IF EXISTS aliases")

    # l0_events
    op.execute("ALTER TABLE l0_events DROP COLUMN IF EXISTS is_extracted")
    op.execute("ALTER TABLE l0_events DROP COLUMN IF EXISTS occurred_at")
    op.execute("ALTER TABLE l0_events DROP COLUMN IF EXISTS event_kind")
    op.execute("ALTER TABLE l0_events DROP COLUMN IF EXISTS actor_external_id")
    op.execute("ALTER TABLE l0_events DROP COLUMN IF EXISTS access_context")
    op.execute("ALTER TABLE l0_events DROP COLUMN IF EXISTS access_level")
    op.execute("ALTER TABLE l0_events DROP COLUMN IF EXISTS raw_text")

    # --------------------------------------------------------------------------
    # Drop extraction_runs table
    # --------------------------------------------------------------------------
    op.drop_table("extraction_runs")
