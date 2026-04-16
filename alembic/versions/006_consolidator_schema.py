"""Consolidator schema: integrator_actions table + integrator_runs extensions

Revision ID: 006
Revises: 005b
Create Date: 2026-04-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "006"
down_revision: str | None = "005b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --------------------------------------------------------------------------
    # 1. CREATE TABLE integrator_actions
    # --------------------------------------------------------------------------
    op.create_table(
        "integrator_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("pass_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'applied'")),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("targets", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("inverse", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("trace_id", UUID(as_uuid=True), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("snapshot_schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_ia_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["integrator_runs.workspace_id", "integrator_runs.id"],
            name="fk_ia_run",
        ),
    )

    op.execute("CREATE INDEX idx_ia_run ON integrator_actions (run_id, pass_number, created_at)")
    op.execute("CREATE INDEX idx_ia_entity ON integrator_actions (workspace_id, entity_id, created_at)")
    op.execute("CREATE INDEX idx_ia_type ON integrator_actions (workspace_id, action_type, created_at)")

    op.execute("ALTER TABLE integrator_actions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON integrator_actions "
        "USING (workspace_id = current_setting('app.workspace_id', true)::uuid)"
    )
    op.execute("ALTER TABLE integrator_actions FORCE ROW LEVEL SECURITY")

    # --------------------------------------------------------------------------
    # 2. EXTEND integrator_runs
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE integrator_runs ADD COLUMN IF NOT EXISTS pass_count INT DEFAULT 1")
    op.execute("ALTER TABLE integrator_runs ADD COLUMN IF NOT EXISTS convergence_reason TEXT")


def downgrade() -> None:
    # --------------------------------------------------------------------------
    # Remove integrator_runs extensions
    # --------------------------------------------------------------------------
    op.execute("ALTER TABLE integrator_runs DROP COLUMN IF EXISTS convergence_reason")
    op.execute("ALTER TABLE integrator_runs DROP COLUMN IF EXISTS pass_count")

    # --------------------------------------------------------------------------
    # Drop integrator_actions
    # --------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_ia_type")
    op.execute("DROP INDEX IF EXISTS idx_ia_entity")
    op.execute("DROP INDEX IF EXISTS idx_ia_run")
    op.execute("DROP POLICY IF EXISTS workspace_isolation ON integrator_actions")
    op.execute("ALTER TABLE integrator_actions DISABLE ROW LEVEL SECURITY")
    op.drop_table("integrator_actions")
