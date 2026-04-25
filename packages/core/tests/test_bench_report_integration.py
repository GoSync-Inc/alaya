"""Integration test for scripts.bench_report.format_summary against real Postgres schema.

Purpose: catch production-schema mismatches (column renames, type changes, table
renames) at test time rather than during a manual smoke run. The unit tests in
tests/test_bench_report.py use SQLite with a synthetic schema — they cannot catch
Postgres-specific column or constraint mismatches.

This test uses the `migrated_container` fixture from conftest.py (same harness
as other integration tests), which runs `alembic upgrade head` and provisions a
real pgvector Postgres instance.

Requires Docker (testcontainers). Run with:
    uv run pytest -m integration -q
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import NullPool, create_engine, text

# scripts/ is on the Python path via pyproject.toml pythonpath=["."]
from scripts.bench_report import format_summary

if TYPE_CHECKING:
    from testcontainers.postgres import PostgresContainer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ANCHOR_DT = datetime(2024, 7, 1, 10, 0, 0, tzinfo=UTC)


def _ts(offset_seconds: int = 0) -> str:
    return (ANCHOR_DT + timedelta(seconds=offset_seconds)).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _sync_url(container: PostgresContainer) -> str:
    """Convert asyncpg URL to psycopg2-compatible sync URL."""
    return container.get_connection_url().replace("postgresql+asyncpg://", "postgresql+psycopg2://")


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_format_summary_against_real_postgres_schema(migrated_container: PostgresContainer) -> None:
    """format_summary() must execute without error against the real alembic schema.

    Inserts minimal rows into the real tables and asserts the returned manifest
    contains populated extraction_runs, integrator_runs, and pipeline_traces lists
    with expected fields.
    """
    sync_engine = create_engine(_sync_url(migrated_container), poolclass=NullPool)
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    int_run_id = uuid.uuid4()
    trace_id = uuid.uuid4()
    int_trace_id = uuid.uuid4()

    with sync_engine.connect() as conn:
        # Insert workspace (required for FK integrity)
        conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": str(ws_id), "name": "Bench Test WS", "slug": f"bench-test-{ws_id.hex[:8]}"},
        )
        # Insert extraction_run
        conn.execute(
            text(
                """
                INSERT INTO extraction_runs
                    (id, workspace_id, status, tokens_in, tokens_out, tokens_cached,
                     cache_write_5m_tokens, cache_write_1h_tokens,
                     cost_usd, entities_created, entities_merged, relations_created,
                     claims_created, claims_superseded, completed_at)
                VALUES (:id, :ws, 'completed', 500, 200, 100, 50, 10,
                        0.005, 3, 0, 1, 5, 0, :completed_at)
                """
            ),
            {"id": str(run_id), "ws": str(ws_id), "completed_at": _ts(60)},
        )
        # Insert integrator_run
        conn.execute(
            text(
                """
                INSERT INTO integrator_runs
                    (id, workspace_id, trigger, status, tokens_used,
                     tokens_in, tokens_out, tokens_cached,
                     cache_write_5m_tokens, cache_write_1h_tokens,
                     cost_usd, duration_ms, started_at, completed_at)
                VALUES (:id, :ws, 'manual', 'completed', 120,
                        100, 20, 30, 5, 2,
                        0.002, 800, :started_at, :completed_at)
                """
            ),
            {"id": str(int_run_id), "ws": str(ws_id), "started_at": _ts(120), "completed_at": _ts(180)},
        )
        # Insert pipeline_trace linked to extraction_run
        conn.execute(
            text(
                """
                INSERT INTO pipeline_traces
                    (id, workspace_id, extraction_run_id, stage, tokens_used,
                     tokens_in, tokens_out, tokens_cached,
                     cache_write_5m_tokens, cache_write_1h_tokens,
                     cost_usd, duration_ms, created_at)
                VALUES (:id, :ws, :run_id, 'cortex:classify', 50,
                        40, 10, 20, 5, 0,
                        0.001, 150, :created_at)
                """
            ),
            {
                "id": str(trace_id),
                "ws": str(ws_id),
                "run_id": str(run_id),
                "created_at": _ts(30),
            },
        )
        # Insert pipeline_trace linked to integrator_run (event_id=NULL)
        conn.execute(
            text(
                """
                INSERT INTO pipeline_traces
                    (id, workspace_id, integrator_run_id, stage, tokens_used,
                     tokens_in, tokens_out, tokens_cached,
                     cache_write_5m_tokens, cache_write_1h_tokens,
                     cost_usd, duration_ms, created_at)
                VALUES (:id, :ws, :int_run_id, 'integrator:dedup', 70,
                        60, 10, 15, 3, 1,
                        0.001, 200, :created_at)
                """
            ),
            {
                "id": str(int_trace_id),
                "ws": str(ws_id),
                "int_run_id": str(int_run_id),
                "created_at": _ts(130),
            },
        )
        conn.commit()

        # Call format_summary against the real Postgres schema
        data, summary_md = format_summary(conn, ws_id, ANCHOR_DT)

    # ── Manifest data assertions ──

    # extraction_runs list populated with expected fields
    assert len(data["extraction_runs"]) == 1, "Expected 1 extraction_run in manifest"
    er = data["extraction_runs"][0]
    assert er["id"] == str(run_id)
    assert er["status"] == "completed"
    assert er["tokens_in"] == 500
    assert er["tokens_out"] == 200
    assert er["tokens_cached"] == 100
    assert "cost_usd" in er
    assert "entities_created" in er

    # integrator_runs list populated with expected fields
    assert len(data["integrator_runs"]) == 1, "Expected 1 integrator_run in manifest"
    ir = data["integrator_runs"][0]
    assert ir["id"] == str(int_run_id)
    assert ir["status"] == "completed"
    assert ir["tokens_used"] == 120
    assert "cost_usd" in ir

    # pipeline_traces: 2 rows (one per trace)
    assert len(data["pipeline_traces"]) == 2, "Expected 2 pipeline_traces in manifest"
    stages = {t["stage"] for t in data["pipeline_traces"]}
    assert "cortex:classify" in stages
    assert "integrator:dedup" in stages

    # integrator_run_id populated on the integrator trace, None on the extraction trace
    for t in data["pipeline_traces"]:
        if t["stage"] == "integrator:dedup":
            assert t["integrator_run_id"] == str(int_run_id), "integrator_run_id missing on integrator trace"
        else:
            assert t["integrator_run_id"] is None, "integrator_run_id should be None on extraction trace"

    # Granular token columns present on pipeline traces
    for t in data["pipeline_traces"]:
        assert "tokens_in" in t
        assert "tokens_cached" in t
        assert "cache_write_5m_tokens" in t
        assert "cache_write_1h_tokens" in t

    # cache_hit_ratio_per_stage computed (non-empty since traces have granular data)
    assert "cache_hit_ratio_per_stage" in data
    assert len(data["cache_hit_ratio_per_stage"]) > 0

    # quality_proxies present
    assert "quality_proxies" in data
    qp = data["quality_proxies"]
    assert "description_rate" in qp
    assert "claims_per_entity" in qp
    assert "run_failure_count" in qp
    assert qp["run_failure_count"] == 0

    # ── Markdown assertions ──
    assert "## Latency" in summary_md
    assert "## Token Usage" in summary_md
    assert "## Cost" in summary_md
    assert "## Quality Proxies" in summary_md
    assert "## Run Health" in summary_md

    sync_engine.dispose()
