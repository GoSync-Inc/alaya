"""RLS policy coverage test — verifies all workspace-scoped tables have FORCE RLS.

Regenerate KNOWN_RLS_TABLES when migrations add new RLS-protected tables.
Tables are enumerated from migrations 001/003/004/006/007 that apply
ENABLE ROW LEVEL SECURITY + FORCE ROW LEVEL SECURITY.

Migration 002 removes FORCE from api_keys (auth bootstrap table) — api_keys
is intentionally excluded from this set.
"""

import pytest
from sqlalchemy import text

# All tables that must have both relrowsecurity AND relforcerowsecurity = true
# after all migrations run. Update this when adding new workspace-scoped tables.
# Regenerate when migrations add new RLS-protected tables.
KNOWN_RLS_TABLES: frozenset[str] = frozenset(
    {
        # Migration 001: initial workspace-scoped tables
        "l0_events",
        "entity_type_definitions",
        "predicate_definitions",
        "l1_entities",
        "entity_external_ids",
        "l1_relations",
        "l2_claims",
        "l3_tree_nodes",
        "vector_chunks",
        "workspace_members",
        "access_groups",
        "resource_grants",
        "audit_log",
        # Migration 003: extraction schema
        "extraction_runs",
        # Migration 004: intelligence pipeline tables
        "l0_chunks",
        "pipeline_traces",
        "integrator_runs",
        # Migration 006: consolidator schema
        "integrator_actions",
        # Migration 007: multi-tenant hardening join tables
        "claim_sources",
        "relation_sources",
        "access_group_members",
    }
)


@pytest.mark.integration
async def test_rls_policy_coverage(engine_superuser) -> None:
    """Every table in KNOWN_RLS_TABLES must have relrowsecurity AND relforcerowsecurity.

    Uses the superuser engine because pg_class is readable by any role, but
    the superuser connection ensures we see all schemas unfiltered.

    On failure the assertion message lists the tables that are missing FORCE RLS.
    """
    async with engine_superuser.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT relname "
                "FROM pg_class "
                "WHERE relname = ANY(:tables) "
                "  AND (NOT relrowsecurity OR NOT relforcerowsecurity)"
            ),
            {"tables": list(KNOWN_RLS_TABLES)},
        )
        missing = [row[0] for row in result]

    assert not missing, (
        f"The following tables are in KNOWN_RLS_TABLES but do NOT have "
        f"relrowsecurity=true AND relforcerowsecurity=true: {sorted(missing)}\n"
        f"Either enable FORCE ROW LEVEL SECURITY on these tables via a migration, "
        f"or remove them from KNOWN_RLS_TABLES if they are intentionally excluded."
    )
