"""Multi-tenant hardening: workspace_id + composite FK + RLS on join tables

Revision ID: 007
Revises: 006
Create Date: 2026-04-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --------------------------------------------------------------------------
    # 1. Add workspace_id column (nullable) to the three join tables
    # --------------------------------------------------------------------------
    op.add_column("claim_sources", sa.Column("workspace_id", UUID(as_uuid=True), nullable=True))
    op.add_column("relation_sources", sa.Column("workspace_id", UUID(as_uuid=True), nullable=True))
    op.add_column("access_group_members", sa.Column("workspace_id", UUID(as_uuid=True), nullable=True))

    # --------------------------------------------------------------------------
    # 2. Backfill workspace_id from parent tables
    # --------------------------------------------------------------------------
    op.execute("UPDATE claim_sources cs SET workspace_id = c.workspace_id FROM l2_claims c WHERE cs.claim_id = c.id")
    op.execute(
        "UPDATE relation_sources rs SET workspace_id = r.workspace_id FROM l1_relations r WHERE rs.relation_id = r.id"
    )
    op.execute(
        "UPDATE access_group_members agm "
        "SET workspace_id = ag.workspace_id "
        "FROM access_groups ag "
        "WHERE agm.group_id = ag.id"
    )

    # --------------------------------------------------------------------------
    # 3. Set NOT NULL on workspace_id columns
    # --------------------------------------------------------------------------
    op.alter_column("claim_sources", "workspace_id", nullable=False)
    op.alter_column("relation_sources", "workspace_id", nullable=False)
    op.alter_column("access_group_members", "workspace_id", nullable=False)

    # --------------------------------------------------------------------------
    # 4. Drop old single-column FKs
    # --------------------------------------------------------------------------
    op.drop_constraint("claim_sources_claim_id_fkey", "claim_sources", type_="foreignkey")
    op.drop_constraint("claim_sources_event_id_fkey", "claim_sources", type_="foreignkey")
    op.drop_constraint("relation_sources_relation_id_fkey", "relation_sources", type_="foreignkey")
    op.drop_constraint("relation_sources_event_id_fkey", "relation_sources", type_="foreignkey")
    op.drop_constraint("access_group_members_group_id_fkey", "access_group_members", type_="foreignkey")
    op.drop_constraint("access_group_members_member_id_fkey", "access_group_members", type_="foreignkey")

    # --------------------------------------------------------------------------
    # 5. Add composite FKs
    # --------------------------------------------------------------------------
    # claim_sources → l2_claims (workspace_id, claim_id)
    op.create_foreign_key(
        "fk_claim_sources_claim",
        "claim_sources",
        "l2_claims",
        ["workspace_id", "claim_id"],
        ["workspace_id", "id"],
    )
    # claim_sources → l0_events (workspace_id, event_id)
    op.create_foreign_key(
        "fk_claim_sources_event",
        "claim_sources",
        "l0_events",
        ["workspace_id", "event_id"],
        ["workspace_id", "id"],
    )
    # relation_sources → l1_relations (workspace_id, relation_id)
    op.create_foreign_key(
        "fk_relation_sources_relation",
        "relation_sources",
        "l1_relations",
        ["workspace_id", "relation_id"],
        ["workspace_id", "id"],
    )
    # relation_sources → l0_events (workspace_id, event_id)
    op.create_foreign_key(
        "fk_relation_sources_event",
        "relation_sources",
        "l0_events",
        ["workspace_id", "event_id"],
        ["workspace_id", "id"],
    )
    # access_group_members → access_groups (workspace_id, group_id)
    op.create_foreign_key(
        "fk_agm_group",
        "access_group_members",
        "access_groups",
        ["workspace_id", "group_id"],
        ["workspace_id", "id"],
    )
    # access_group_members → workspace_members (workspace_id, member_id)
    op.create_foreign_key(
        "fk_agm_member",
        "access_group_members",
        "workspace_members",
        ["workspace_id", "member_id"],
        ["workspace_id", "id"],
    )

    # --------------------------------------------------------------------------
    # 6. Create indexes CONCURRENTLY (may have data in user installations)
    #    Note: CONCURRENTLY cannot run inside a transaction; use op.execute directly.
    # --------------------------------------------------------------------------
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_claim_sources_ws ON claim_sources (workspace_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relation_sources_ws ON relation_sources (workspace_id)")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_access_group_members_ws ON access_group_members (workspace_id)"
    )

    # --------------------------------------------------------------------------
    # 7. Enable RLS + FORCE + workspace isolation policy on all three tables
    # --------------------------------------------------------------------------
    for table in ("claim_sources", "relation_sources", "access_group_members"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY workspace_isolation ON {table} "
            "USING (workspace_id = current_setting('app.workspace_id', true)::uuid) "
            "WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)"
        )


def downgrade() -> None:
    # --------------------------------------------------------------------------
    # 1. Drop RLS policies + disable
    # --------------------------------------------------------------------------
    for table in ("claim_sources", "relation_sources", "access_group_members"):
        op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # --------------------------------------------------------------------------
    # 2. Drop indexes
    # --------------------------------------------------------------------------
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_access_group_members_ws")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_relation_sources_ws")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_claim_sources_ws")

    # --------------------------------------------------------------------------
    # 3. Drop composite FKs
    # --------------------------------------------------------------------------
    op.drop_constraint("fk_agm_member", "access_group_members", type_="foreignkey")
    op.drop_constraint("fk_agm_group", "access_group_members", type_="foreignkey")
    op.drop_constraint("fk_relation_sources_event", "relation_sources", type_="foreignkey")
    op.drop_constraint("fk_relation_sources_relation", "relation_sources", type_="foreignkey")
    op.drop_constraint("fk_claim_sources_event", "claim_sources", type_="foreignkey")
    op.drop_constraint("fk_claim_sources_claim", "claim_sources", type_="foreignkey")

    # --------------------------------------------------------------------------
    # 4. Drop workspace_id column (CASCADE drops any dependent indexes)
    # --------------------------------------------------------------------------
    op.drop_column("access_group_members", "workspace_id")
    op.drop_column("relation_sources", "workspace_id")
    op.drop_column("claim_sources", "workspace_id")

    # --------------------------------------------------------------------------
    # 5. Recreate original single-column FKs
    # --------------------------------------------------------------------------
    op.create_foreign_key(
        "claim_sources_claim_id_fkey",
        "claim_sources",
        "l2_claims",
        ["claim_id"],
        ["id"],
    )
    op.create_foreign_key(
        "claim_sources_event_id_fkey",
        "claim_sources",
        "l0_events",
        ["event_id"],
        ["id"],
    )
    op.create_foreign_key(
        "relation_sources_relation_id_fkey",
        "relation_sources",
        "l1_relations",
        ["relation_id"],
        ["id"],
    )
    op.create_foreign_key(
        "relation_sources_event_id_fkey",
        "relation_sources",
        "l0_events",
        ["event_id"],
        ["id"],
    )
    op.create_foreign_key(
        "access_group_members_group_id_fkey",
        "access_group_members",
        "access_groups",
        ["group_id"],
        ["id"],
    )
    op.create_foreign_key(
        "access_group_members_member_id_fkey",
        "access_group_members",
        "workspace_members",
        ["member_id"],
        ["id"],
    )
