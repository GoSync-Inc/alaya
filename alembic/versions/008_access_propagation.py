"""ACL propagation for retrieval filtering.

Revision ID: 008
Revises: 007
Create Date: 2026-04-25
"""

import contextlib
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context as alembic_context
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FORCE_RLS_PARENTS: tuple[str, ...] = ("l0_events", "l2_claims", "vector_chunks", "claim_sources")


def _restore_force_rls_best_effort() -> None:
    for table in _FORCE_RLS_PARENTS:
        with contextlib.suppress(Exception):
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    try:
        _upgrade_impl()
    except Exception:
        _restore_force_rls_best_effort()
        raise


def _upgrade_impl() -> None:
    # ---- 0. pgvector version check ----------------------------------------
    op.execute("""
        DO $$
        DECLARE v text;
        BEGIN
            SELECT extversion INTO v FROM pg_extension WHERE extname = 'vector';
            IF v IS NULL THEN
                RAISE EXCEPTION 'pgvector extension is not installed';
            END IF;
            IF string_to_array(v, '.')::int[] < ARRAY[0,8]::int[] THEN
                RAISE EXCEPTION 'pgvector >= 0.8 is required for Run 6.2 ACL filtering (found %).', v;
            END IF;
        END $$;
    """)

    # ---- 1. Temporarily remove FORCE RLS on tables we need to read/update --
    for table in _FORCE_RLS_PARENTS:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

    # ---- 2. Create tier helpers before backfill uses them ------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION tier_rank(lvl text) RETURNS int
        LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE lvl
                WHEN 'public'     THEN 0
                WHEN 'channel'    THEN 1
                WHEN 'private'    THEN 2
                WHEN 'restricted' THEN 3
                ELSE 3
            END;
        $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION rank_to_level(rank int) RETURNS text
        LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE rank
                WHEN 0 THEN 'public'
                WHEN 1 THEN 'channel'
                WHEN 2 THEN 'private'
                WHEN 3 THEN 'restricted'
                ELSE 'restricted'
            END;
        $$;
    """)

    # ---- 3. Add vector_chunks.access_level nullable for backfill -----------
    op.execute("ALTER TABLE vector_chunks ADD COLUMN IF NOT EXISTS access_level text")

    # ---- 4a. Preflight duplicate claim_sources rows -----------------------
    if not alembic_context.is_offline_mode():
        bind = op.get_bind()
        duplicate_count = bind.execute(
            sa.text("""
                SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                    SELECT COUNT(*) AS cnt
                    FROM claim_sources
                    GROUP BY workspace_id, claim_id, event_id
                    HAVING COUNT(*) > 1
                ) duplicate_claim_sources
            """)
        ).scalar_one()
        if duplicate_count:
            raise RuntimeError(
                f"Migration 008 aborted: {duplicate_count} duplicate rows in claim_sources "
                "(workspace_id, claim_id, event_id). Dedupe manually before re-running, e.g.:\n"
                "  DELETE FROM claim_sources cs1 USING claim_sources cs2 "
                "WHERE cs1.ctid < cs2.ctid AND cs1.workspace_id = cs2.workspace_id "
                "AND cs1.claim_id = cs2.claim_id AND cs1.event_id = cs2.event_id;"
            )

    # ---- 4b. Unique index concurrently for ON CONFLICT --------------------
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
            uq_claim_sources_ws_claim_event
            ON claim_sources (workspace_id, claim_id, event_id)
        """)

    # ---- 5. Backfill claim_sources from legacy source_event_id -------------
    op.execute("""
        INSERT INTO claim_sources (id, workspace_id, claim_id, event_id, created_at)
        SELECT gen_random_uuid(), c.workspace_id, c.id, c.source_event_id, c.created_at
        FROM l2_claims c
        WHERE c.source_event_id IS NOT NULL
        ON CONFLICT (workspace_id, claim_id, event_id) DO NOTHING
    """)

    # ---- 6. Backfill vector_chunks.access_level per source_type ------------
    op.execute("""
        UPDATE vector_chunks vc
        SET access_level = rank_to_level(tier_rank(e.access_level))
        FROM l0_events e
        WHERE vc.source_type = 'event'
          AND vc.source_id = e.id
          AND vc.workspace_id = e.workspace_id
    """)

    op.execute("""
        UPDATE vector_chunks vc
        SET access_level = rank_to_level(
            COALESCE(
                (
                    SELECT MAX(tier_rank(e.access_level))
                    FROM claim_sources cs
                    JOIN l0_events e
                      ON e.id = cs.event_id AND e.workspace_id = cs.workspace_id
                    WHERE cs.claim_id = vc.source_id
                      AND cs.workspace_id = vc.workspace_id
                ),
                3
            )
        )
        WHERE vc.source_type = 'claim'
    """)

    op.execute("""
        UPDATE vector_chunks vc
        SET access_level = rank_to_level(
            COALESCE(
                (
                    SELECT MAX(tier_rank(e.access_level))
                    FROM l2_claims c
                    JOIN claim_sources cs
                      ON cs.claim_id = c.id AND cs.workspace_id = c.workspace_id
                    JOIN l0_events e
                      ON e.id = cs.event_id AND e.workspace_id = cs.workspace_id
                    WHERE c.entity_id = vc.source_id
                      AND c.workspace_id = vc.workspace_id
                ),
                3
            )
        )
        WHERE vc.source_type = 'entity'
    """)

    op.execute("""
        UPDATE vector_chunks
        SET access_level = 'restricted'
        WHERE access_level IS NULL
    """)

    # ---- 7. Set NOT NULL + default on vector_chunks.access_level -----------
    op.alter_column("vector_chunks", "access_level", nullable=False, server_default="restricted")

    # ---- 8-10. Supporting btree indexes concurrently -----------------------
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
            ix_vector_chunks_ws_access
            ON vector_chunks (workspace_id, access_level)
        """)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
            ix_l2_claims_active_ws_entity
            ON l2_claims (workspace_id, entity_id)
            WHERE status = 'active'
        """)

    # ---- 11. Current allowed access helper: STABLE, not leakproof ----------
    op.execute("""
        CREATE OR REPLACE FUNCTION alaya_current_allowed_access()
        RETURNS text[]
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            g text;
        BEGIN
            BEGIN
                g := current_setting('app.allowed_access_levels', true);
            EXCEPTION WHEN others THEN
                g := NULL;
            END;
            IF g IS NULL OR g = '' THEN
                RETURN ARRAY['public']::text[];
            END IF;
            RETURN string_to_array(g, ',');
        END
        $$;
    """)

    # ---- 12. Non-materialized claim effective access view ------------------
    op.execute("""
        CREATE OR REPLACE VIEW claim_effective_access
        WITH (security_invoker = true) AS
        SELECT
            c.workspace_id,
            c.id AS claim_id,
            COALESCE(MAX(tier_rank(e.access_level)), 3) AS max_tier_rank
        FROM l2_claims c
        LEFT JOIN claim_sources cs
          ON cs.claim_id = c.id AND cs.workspace_id = c.workspace_id
        LEFT JOIN l0_events e
          ON e.id = cs.event_id AND e.workspace_id = cs.workspace_id
        GROUP BY c.workspace_id, c.id
    """)

    # ---- 13. Restamp vector chunks on l0_events.access_level update --------
    op.execute("""
        CREATE OR REPLACE FUNCTION restamp_vector_chunks_on_event_acl_change()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.access_level IS DISTINCT FROM OLD.access_level THEN
                UPDATE vector_chunks vc
                SET access_level = rank_to_level(tier_rank(NEW.access_level))
                WHERE vc.source_type = 'event'
                  AND vc.source_id = NEW.id
                  AND vc.workspace_id = NEW.workspace_id;

                UPDATE vector_chunks vc
                SET access_level = rank_to_level(
                    COALESCE(
                        (
                            SELECT MAX(tier_rank(e2.access_level))
                            FROM claim_sources cs2
                            JOIN l0_events e2
                              ON e2.id = cs2.event_id AND e2.workspace_id = cs2.workspace_id
                            WHERE cs2.claim_id = vc.source_id
                              AND cs2.workspace_id = vc.workspace_id
                        ),
                        3
                    )
                )
                WHERE vc.source_type = 'claim'
                  AND vc.workspace_id = NEW.workspace_id
                  AND vc.source_id IN (
                      SELECT cs.claim_id
                      FROM claim_sources cs
                      WHERE cs.event_id = NEW.id
                        AND cs.workspace_id = NEW.workspace_id
                  );

                UPDATE vector_chunks vc
                SET access_level = rank_to_level(
                    COALESCE(
                        (
                            SELECT MAX(tier_rank(e3.access_level))
                            FROM l2_claims c3
                            JOIN claim_sources cs3
                              ON cs3.claim_id = c3.id AND cs3.workspace_id = c3.workspace_id
                            JOIN l0_events e3
                              ON e3.id = cs3.event_id AND e3.workspace_id = cs3.workspace_id
                            WHERE c3.entity_id = vc.source_id
                              AND c3.workspace_id = vc.workspace_id
                        ),
                        3
                    )
                )
                WHERE vc.source_type = 'entity'
                  AND vc.workspace_id = NEW.workspace_id
                  AND EXISTS (
                      SELECT 1
                      FROM l2_claims c4
                      JOIN claim_sources cs4
                        ON cs4.claim_id = c4.id AND cs4.workspace_id = c4.workspace_id
                      WHERE c4.entity_id = vc.source_id
                        AND c4.workspace_id = vc.workspace_id
                        AND cs4.event_id = NEW.id
                  );
            END IF;
            RETURN NEW;
        END
        $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_restamp_vector_chunks_on_event_acl
        AFTER UPDATE OF access_level ON l0_events
        FOR EACH ROW
        EXECUTE FUNCTION restamp_vector_chunks_on_event_acl_change();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION restamp_vector_chunks_on_claim_sources_change()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            affected_claim_id uuid;
            affected_workspace_id uuid;
            affected_entity_id uuid;
        BEGIN
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                affected_claim_id := NEW.claim_id;
                affected_workspace_id := NEW.workspace_id;

                SELECT c.entity_id
                INTO affected_entity_id
                FROM l2_claims c
                WHERE c.id = affected_claim_id
                  AND c.workspace_id = affected_workspace_id;

                UPDATE vector_chunks vc
                SET access_level = rank_to_level(COALESCE(
                    (
                        SELECT MAX(tier_rank(e.access_level))
                        FROM claim_sources cs
                        JOIN l0_events e
                          ON e.id = cs.event_id AND e.workspace_id = cs.workspace_id
                        WHERE cs.claim_id = affected_claim_id
                          AND cs.workspace_id = affected_workspace_id
                    ), 3
                ))
                WHERE vc.source_type = 'claim'
                  AND vc.source_id = affected_claim_id
                  AND vc.workspace_id = affected_workspace_id;

                IF affected_entity_id IS NOT NULL THEN
                    UPDATE vector_chunks vc
                    SET access_level = rank_to_level(COALESCE(
                        (
                            SELECT MAX(tier_rank(e.access_level))
                            FROM l2_claims c
                            JOIN claim_sources cs
                              ON cs.claim_id = c.id AND cs.workspace_id = c.workspace_id
                            JOIN l0_events e
                              ON e.id = cs.event_id AND e.workspace_id = cs.workspace_id
                            WHERE c.entity_id = affected_entity_id
                              AND c.workspace_id = affected_workspace_id
                        ), 3
                    ))
                    WHERE vc.source_type = 'entity'
                      AND vc.source_id = affected_entity_id
                      AND vc.workspace_id = affected_workspace_id;
                END IF;
            END IF;

            IF TG_OP IN ('DELETE', 'UPDATE') THEN
                affected_claim_id := OLD.claim_id;
                affected_workspace_id := OLD.workspace_id;

                IF TG_OP = 'UPDATE'
                   AND affected_claim_id = NEW.claim_id
                   AND affected_workspace_id = NEW.workspace_id THEN
                    RETURN NEW;
                END IF;

                SELECT c.entity_id
                INTO affected_entity_id
                FROM l2_claims c
                WHERE c.id = affected_claim_id
                  AND c.workspace_id = affected_workspace_id;

                UPDATE vector_chunks vc
                SET access_level = rank_to_level(COALESCE(
                    (
                        SELECT MAX(tier_rank(e.access_level))
                        FROM claim_sources cs
                        JOIN l0_events e
                          ON e.id = cs.event_id AND e.workspace_id = cs.workspace_id
                        WHERE cs.claim_id = affected_claim_id
                          AND cs.workspace_id = affected_workspace_id
                    ), 3
                ))
                WHERE vc.source_type = 'claim'
                  AND vc.source_id = affected_claim_id
                  AND vc.workspace_id = affected_workspace_id;

                IF affected_entity_id IS NOT NULL THEN
                    UPDATE vector_chunks vc
                    SET access_level = rank_to_level(COALESCE(
                        (
                            SELECT MAX(tier_rank(e.access_level))
                            FROM l2_claims c
                            JOIN claim_sources cs
                              ON cs.claim_id = c.id AND cs.workspace_id = c.workspace_id
                            JOIN l0_events e
                              ON e.id = cs.event_id AND e.workspace_id = cs.workspace_id
                            WHERE c.entity_id = affected_entity_id
                              AND c.workspace_id = affected_workspace_id
                        ), 3
                    ))
                    WHERE vc.source_type = 'entity'
                      AND vc.source_id = affected_entity_id
                      AND vc.workspace_id = affected_workspace_id;
                END IF;
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END
        $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_restamp_vector_chunks_on_claim_sources
        AFTER INSERT OR UPDATE OR DELETE ON claim_sources
        FOR EACH ROW
        EXECUTE FUNCTION restamp_vector_chunks_on_claim_sources_change();
    """)

    # ---- 14. Restore FORCE RLS --------------------------------------------
    for table in _FORCE_RLS_PARENTS:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    try:
        _downgrade_impl()
    except Exception:
        _restore_force_rls_best_effort()
        raise


def _downgrade_impl() -> None:
    for table in _FORCE_RLS_PARENTS:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER IF EXISTS trg_restamp_vector_chunks_on_claim_sources ON claim_sources")
    op.execute("DROP FUNCTION IF EXISTS restamp_vector_chunks_on_claim_sources_change()")
    op.execute("DROP TRIGGER IF EXISTS trg_restamp_vector_chunks_on_event_acl ON l0_events")
    op.execute("DROP FUNCTION IF EXISTS restamp_vector_chunks_on_event_acl_change()")
    op.execute("DROP VIEW IF EXISTS claim_effective_access")
    op.execute("DROP FUNCTION IF EXISTS alaya_current_allowed_access()")

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_l2_claims_active_ws_entity")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_vector_chunks_ws_access")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_claim_sources_ws_claim_event")

    op.drop_column("vector_chunks", "access_level")
    op.execute("DROP FUNCTION IF EXISTS rank_to_level(int)")
    op.execute("DROP FUNCTION IF EXISTS tier_rank(text)")
    # claim_sources backfill rows left in place because they are legitimate provenance data.

    for table in _FORCE_RLS_PARENTS:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
