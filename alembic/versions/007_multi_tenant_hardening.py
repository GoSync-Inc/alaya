"""Multi-tenant hardening: workspace_id + composite FK + RLS on join tables

Revision ID: 007
Revises: 006
Create Date: 2026-04-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import context as alembic_context
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Parent tables that carry FORCE ROW LEVEL SECURITY and are referenced in the
# backfill / preflight queries. We must temporarily remove FORCE so the
# migration (running as TABLE OWNER) can read them without app.workspace_id
# being set. Restored at step 8 after all join-table RLS has been applied.
_FORCE_RLS_PARENTS: tuple[str, ...] = (
    "l2_claims",
    "l1_relations",
    "l0_events",
    "access_groups",
    "workspace_members",
)


def upgrade() -> None:
    # --------------------------------------------------------------------------
    # Overview of steps:
    #   0.   Temporarily remove FORCE RLS on parent tables (restored at step 8)
    #   1.   Add workspace_id column (nullable)
    #   1.5. Abort if any legacy join row has a cross-workspace reference
    #   2.   Backfill workspace_id from parent tables
    #   3.   Set NOT NULL
    #   4.   Drop old single-column FKs
    #   5.   Add composite FKs
    #   6.   Create indexes CONCURRENTLY
    #   7.   Enable RLS + FORCE + workspace isolation policy on join tables
    #   8.   Restore FORCE RLS on parent tables
    # --------------------------------------------------------------------------

    # --------------------------------------------------------------------------
    # 0. Temporarily remove FORCE RLS on parent tables so the backfill and the
    # preflight cross-workspace check can read them. The migration is expected
    # to run as TABLE OWNER; FORCE RLS applies to the owner too, which would
    # hide the parent rows when app.workspace_id is not set. We restore FORCE
    # at step 8.
    # --------------------------------------------------------------------------
    for _t in _FORCE_RLS_PARENTS:
        op.execute(f"ALTER TABLE {_t} NO FORCE ROW LEVEL SECURITY")

    # --------------------------------------------------------------------------
    # 1. Add workspace_id column (nullable) to the three join tables
    # --------------------------------------------------------------------------
    op.add_column("claim_sources", sa.Column("workspace_id", UUID(as_uuid=True), nullable=True))
    op.add_column("relation_sources", sa.Column("workspace_id", UUID(as_uuid=True), nullable=True))
    op.add_column("access_group_members", sa.Column("workspace_id", UUID(as_uuid=True), nullable=True))

    # --------------------------------------------------------------------------
    # 1.5. Abort if any legacy join row has a cross-workspace reference.
    # Pre-007 single-column FKs allowed mismatched parents; we cannot safely
    # backfill workspace_id from only one side when the other side lives in
    # a different workspace. Surface the count so operators can clean up.
    # --------------------------------------------------------------------------
    if alembic_context.is_offline_mode():
        # Offline SQL generation — skip live cross-workspace check. Operators running
        # --sql mode must manually validate join-table integrity before applying the
        # generated SQL.
        pass
    else:
        bind = op.get_bind()

        cross_workspace_queries = {
            "claim_sources": (
                "SELECT COUNT(*) FROM claim_sources cs "
                "JOIN l2_claims c ON cs.claim_id = c.id "
                "JOIN l0_events e ON cs.event_id = e.id "
                "WHERE c.workspace_id <> e.workspace_id"
            ),
            "relation_sources": (
                "SELECT COUNT(*) FROM relation_sources rs "
                "JOIN l1_relations r ON rs.relation_id = r.id "
                "JOIN l0_events e ON rs.event_id = e.id "
                "WHERE r.workspace_id <> e.workspace_id"
            ),
            "access_group_members": (
                "SELECT COUNT(*) FROM access_group_members agm "
                "JOIN access_groups ag ON agm.group_id = ag.id "
                "JOIN workspace_members wm ON agm.member_id = wm.id "
                "WHERE ag.workspace_id <> wm.workspace_id"
            ),
        }

        violations: list[str] = []
        for table, query in cross_workspace_queries.items():
            count = bind.execute(sa.text(query)).scalar_one()
            if count:
                violations.append(f"{table}: {count} rows")

        if violations:
            raise RuntimeError(
                "Migration 007 aborted: legacy cross-workspace rows detected in join tables. "
                "Pre-007 schema allowed mismatched parents; we cannot safely choose a "
                "single workspace_id for these rows. Resolve manually before re-running. "
                "Counts: " + "; ".join(violations)
            )

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
    #    Note: wrapped in autocommit_block() so CONCURRENTLY works inside Alembic — otherwise it would fail under the default transaction-per-migration.
    # --------------------------------------------------------------------------
    with op.get_context().autocommit_block():
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

    # --------------------------------------------------------------------------
    # 8. Restore FORCE RLS on parent tables.
    # --------------------------------------------------------------------------
    for _t in _FORCE_RLS_PARENTS:
        op.execute(f"ALTER TABLE {_t} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # --------------------------------------------------------------------------
    # 0. Temporarily remove FORCE RLS on parent tables for the same reason as
    # in upgrade(): the FK recreation in step 5 reads parent tables and would
    # be blocked by FORCE when app.workspace_id is not set.
    # --------------------------------------------------------------------------
    for _t in _FORCE_RLS_PARENTS:
        op.execute(f"ALTER TABLE {_t} NO FORCE ROW LEVEL SECURITY")

    # --------------------------------------------------------------------------
    # 1. Drop RLS policies + disable
    # --------------------------------------------------------------------------
    for table in ("claim_sources", "relation_sources", "access_group_members"):
        op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # --------------------------------------------------------------------------
    # 2. Drop indexes
    # --------------------------------------------------------------------------
    with op.get_context().autocommit_block():
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

    # --------------------------------------------------------------------------
    # 6. Restore FORCE RLS on parent tables.
    # --------------------------------------------------------------------------
    for _t in _FORCE_RLS_PARENTS:
        op.execute(f"ALTER TABLE {_t} FORCE ROW LEVEL SECURITY")
