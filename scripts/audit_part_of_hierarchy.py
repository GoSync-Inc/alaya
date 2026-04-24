#!/usr/bin/env python3
"""Audit script: detect part_of relations that violate ENTITY_TYPE_TIER_RANK.

Usage:
    python scripts/audit_part_of_hierarchy.py [--workspace-id <uuid>] [--sample-size 20]

Exit code:
    0  — no violations found
    1  — violations found (or DB error)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

# ---------------------------------------------------------------------------
# Tier ranks (keep in sync with alayaos_core.services.workspace)
# ---------------------------------------------------------------------------

ENTITY_TYPE_TIER_RANK: dict[str, int] = {
    "task": 1,
    "project": 2,
    "goal": 3,
    "north_star": 4,
}

_RANKED_SLUGS = list(ENTITY_TYPE_TIER_RANK.keys())


async def _run_audit(database_url: str, workspace_id: uuid.UUID | None, sample_size: int) -> int:
    """Run the audit query and print results. Returns count of violations."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, echo=False)

    # Build WHERE clause for optional workspace filter
    workspace_filter = ""
    params: dict = {"ranked_slugs": _RANKED_SLUGS}
    if workspace_id is not None:
        workspace_filter = "AND r.workspace_id = :workspace_id"
        params["workspace_id"] = workspace_id

    count_sql = text(
        f"""
        SELECT COUNT(*)
        FROM l1_relations r
        JOIN l1_entities se ON se.id = r.source_entity_id AND se.workspace_id = r.workspace_id
        JOIN l1_entities te ON te.id = r.target_entity_id AND te.workspace_id = r.workspace_id
        JOIN entity_type_definitions sd
            ON sd.id = se.entity_type_id AND sd.workspace_id = se.workspace_id
        JOIN entity_type_definitions td
            ON td.id = te.entity_type_id AND td.workspace_id = te.workspace_id
        WHERE r.relation_type = 'part_of'
          AND sd.slug = ANY(:ranked_slugs)
          AND td.slug = ANY(:ranked_slugs)
          AND (
              CASE sd.slug
                  WHEN 'task'       THEN 1
                  WHEN 'project'    THEN 2
                  WHEN 'goal'       THEN 3
                  WHEN 'north_star' THEN 4
              END
          ) >= (
              CASE td.slug
                  WHEN 'task'       THEN 1
                  WHEN 'project'    THEN 2
                  WHEN 'goal'       THEN 3
                  WHEN 'north_star' THEN 4
              END
          )
          {workspace_filter}
        """
    )

    sample_sql = text(
        f"""
        SELECT
            r.id            AS relation_id,
            r.workspace_id,
            se.name         AS source_name,
            sd.slug         AS source_type,
            te.name         AS target_name,
            td.slug         AS target_type
        FROM l1_relations r
        JOIN l1_entities se ON se.id = r.source_entity_id AND se.workspace_id = r.workspace_id
        JOIN l1_entities te ON te.id = r.target_entity_id AND te.workspace_id = r.workspace_id
        JOIN entity_type_definitions sd
            ON sd.id = se.entity_type_id AND sd.workspace_id = se.workspace_id
        JOIN entity_type_definitions td
            ON td.id = te.entity_type_id AND td.workspace_id = te.workspace_id
        WHERE r.relation_type = 'part_of'
          AND sd.slug = ANY(:ranked_slugs)
          AND td.slug = ANY(:ranked_slugs)
          AND (
              CASE sd.slug
                  WHEN 'task'       THEN 1
                  WHEN 'project'    THEN 2
                  WHEN 'goal'       THEN 3
                  WHEN 'north_star' THEN 4
              END
          ) >= (
              CASE td.slug
                  WHEN 'task'       THEN 1
                  WHEN 'project'    THEN 2
                  WHEN 'goal'       THEN 3
                  WHEN 'north_star' THEN 4
              END
          )
          {workspace_filter}
        LIMIT :sample_size
        """
    )
    sample_params = {**params, "sample_size": sample_size}

    async with engine.connect() as conn:
        count_result = await conn.execute(count_sql, params)
        total_count = count_result.scalar() or 0

        print(f"Total violations: {total_count}")

        if total_count > 0:
            sample_result = await conn.execute(sample_sql, sample_params)
            rows = sample_result.mappings().all()
            print(f"\nSample (up to {sample_size}):")
            print(
                f"{'relation_id':<38}  {'source_name':<20}  {'source_type':<12}  {'target_name':<20}  {'target_type'}"
            )
            print("-" * 120)
            for row in rows:
                print(
                    f"{row['relation_id']!s:<38}  "
                    f"{row['source_name']!s:<20}  "
                    f"{row['source_type']!s:<12}  "
                    f"{row['target_name']!s:<20}  "
                    f"{row['target_type']!s}"
                )

    await engine.dispose()
    return total_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit part_of hierarchy violations")
    parser.add_argument("--workspace-id", type=str, default=None, help="Filter by workspace UUID")
    parser.add_argument("--sample-size", type=int, default=20, help="Max rows to print in sample")
    args = parser.parse_args()

    workspace_id: uuid.UUID | None = None
    if args.workspace_id:
        try:
            workspace_id = uuid.UUID(args.workspace_id)
        except ValueError:
            print(f"ERROR: invalid workspace-id UUID: {args.workspace_id}", file=sys.stderr)
            sys.exit(1)

    database_url = os.environ.get("ALAYA_DATABASE_URL", "")
    if not database_url:
        print("ERROR: ALAYA_DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    count = asyncio.run(_run_audit(database_url, workspace_id, args.sample_size))
    sys.exit(0 if count == 0 else 1)


if __name__ == "__main__":
    main()
