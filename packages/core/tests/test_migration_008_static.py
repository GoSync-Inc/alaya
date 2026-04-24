"""Static contract checks for migration 008.

The migration is mostly SQL and trigger code. These checks lock the important
ordering and safety properties from the Run 6.2 design without requiring a live
Postgres container for every unit-test run.
"""

from pathlib import Path

MIGRATION = Path("alembic/versions/008_access_propagation.py")


def _migration_text() -> str:
    return MIGRATION.read_text()


def _section(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def test_migration_008_contains_required_upgrade_ordering() -> None:
    text = _migration_text()

    pgvector_check = text.index("pgvector >= 0.8")
    no_force = text.index("NO FORCE ROW LEVEL SECURITY")
    tier_rank = text.index("CREATE OR REPLACE FUNCTION tier_rank")
    rank_to_level = text.index("CREATE OR REPLACE FUNCTION rank_to_level")
    add_access = text.index("ALTER TABLE vector_chunks ADD COLUMN IF NOT EXISTS access_level")
    duplicate_preflight = text.index("duplicate rows in claim_sources")
    unique_concurrently = text.index("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS")
    claim_sources_backfill = text.index("ON CONFLICT (workspace_id, claim_id, event_id) DO NOTHING")
    vector_backfill = text.index("UPDATE vector_chunks vc")
    set_not_null = text.index('op.alter_column("vector_chunks", "access_level"')
    helper = text.index("CREATE OR REPLACE FUNCTION alaya_current_allowed_access()")
    view = text.index("CREATE OR REPLACE VIEW claim_effective_access")
    trigger = text.index("CREATE TRIGGER trg_restamp_vector_chunks_on_event_acl")
    restore_force = text.rindex("FORCE ROW LEVEL SECURITY")

    assert (
        pgvector_check
        < no_force
        < tier_rank
        < rank_to_level
        < add_access
        < duplicate_preflight
        < unique_concurrently
        < claim_sources_backfill
        < vector_backfill
        < set_not_null
        < helper
        < view
        < trigger
        < restore_force
    )


def test_migration_008_uses_most_restrictive_claim_sources_and_safe_helpers() -> None:
    text = _migration_text()

    assert "LEAKPROOF" not in text
    assert "MATERIALIZED VIEW" not in text
    assert "LANGUAGE plpgsql STABLE" in text
    assert "COALESCE(MAX(tier_rank(e.access_level)), 3)" in text
    assert "WHERE vc.source_type = 'claim'" in text
    assert "SELECT MAX(tier_rank(e2.access_level))" in text
    assert "FROM claim_sources cs2" in text
    assert "WHERE cs2.claim_id = vc.source_id" in text
    assert "WHERE vc.source_type = 'entity'" in text
    assert "SELECT MAX(tier_rank(e3.access_level))" in text
    assert "SET access_level = rank_to_level(tier_rank(e.access_level))" in text
    assert "SET access_level = 'restricted'\n        WHERE access_level IS NULL" in text
    assert 'op.alter_column("vector_chunks", "access_level", nullable=False, server_default="restricted")' in text
    assert "DROP VIEW IF EXISTS claim_effective_access" in text
    assert "DROP FUNCTION IF EXISTS alaya_current_allowed_access()" in text
    assert 'op.execute("DELETE FROM claim_sources' not in text
    assert "op.execute('DELETE FROM claim_sources" not in text
    assert "claim_sources backfill rows left in place" in text


def test_migration_008_vector_access_column_is_reentrant() -> None:
    text = _migration_text()

    assert "ALTER TABLE vector_chunks ADD COLUMN IF NOT EXISTS access_level text" in text
    assert 'op.add_column("vector_chunks"' not in text


def test_migration_008_restamps_vectors_when_claim_sources_change() -> None:
    text = _migration_text()

    trigger_body = _section(
        text,
        "CREATE OR REPLACE FUNCTION restamp_vector_chunks_on_claim_sources_change()",
        "CREATE TRIGGER trg_restamp_vector_chunks_on_claim_sources",
    )

    assert "AFTER INSERT OR UPDATE OR DELETE ON claim_sources" in text
    assert "IF TG_OP IN ('INSERT', 'UPDATE') THEN" in trigger_body
    assert "affected_claim_id := NEW.claim_id" in trigger_body
    assert "affected_workspace_id := NEW.workspace_id" in trigger_body
    assert "IF TG_OP IN ('DELETE', 'UPDATE') THEN" in trigger_body
    assert "affected_claim_id := OLD.claim_id" in trigger_body
    assert "affected_workspace_id := OLD.workspace_id" in trigger_body
    assert "SELECT MAX(tier_rank(e.access_level))" in trigger_body
    assert "WHERE cs.claim_id = affected_claim_id" in trigger_body
    assert "WHERE vc.source_type = 'claim'" in trigger_body
    assert "), 3" in trigger_body
    assert "WHERE vc.source_type = 'entity'" in trigger_body
    assert "), 3" in trigger_body
    assert "DROP TRIGGER IF EXISTS trg_restamp_vector_chunks_on_claim_sources ON claim_sources" in text
    assert "DROP FUNCTION IF EXISTS restamp_vector_chunks_on_claim_sources_change()" in text


def test_migration_008_restores_force_rls_when_upgrade_fails() -> None:
    text = _migration_text()

    upgrade_wrapper = _section(text, "def upgrade() -> None:", "def _upgrade_impl() -> None:")
    restore_helper = _section(text, "def _restore_force_rls_best_effort() -> None:", "def upgrade() -> None:")

    assert "try:" in upgrade_wrapper
    assert "_upgrade_impl()" in upgrade_wrapper
    assert "except Exception:" in upgrade_wrapper
    assert "_restore_force_rls_best_effort()" in upgrade_wrapper
    assert "raise" in upgrade_wrapper
    assert "ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in restore_helper
    assert "with contextlib.suppress(Exception):" in restore_helper


def test_migration_008_restores_force_rls_when_downgrade_fails() -> None:
    text = _migration_text()

    downgrade_wrapper = _section(text, "def downgrade() -> None:", "def _downgrade_impl() -> None:")
    impl_start = text.index("def _downgrade_impl() -> None:")
    impl = text[impl_start:]

    assert "try:" in downgrade_wrapper
    assert "_downgrade_impl()" in downgrade_wrapper
    assert "except Exception:" in downgrade_wrapper
    assert "_restore_force_rls_best_effort()" in downgrade_wrapper
    assert "raise" in downgrade_wrapper
    assert "NO FORCE ROW LEVEL SECURITY" in impl
    assert "FORCE ROW LEVEL SECURITY" in impl
