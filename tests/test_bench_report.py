"""Unit tests for scripts.bench_report and scripts.bench._build_manifest.

Tests run without Docker — uses SQLite in-memory via SQLAlchemy synchronous engine.
Covers:
  - format_summary() returns (dict, str)
  - Markdown shape (sections present)
  - Quality proxy formulas (description_rate, claims_per_entity,
    claims_per_event_stddev, dedup_actions, run_failure_count)
  - Scoping: workspace_id filter and started_at >= started_at filter (per-table timestamp)
  - Secrets policy: no ak_... substring in any output bytes (format_summary + _build_manifest)
  - Empty-workspace edge case (spec #11): result="empty_workspace", exit 0 semantic
"""

from __future__ import annotations

import json
import statistics
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from scripts.bench import EXIT_CACHE_WARM_FAIL, EXIT_SUCCESS, FIXTURES_DIR, _build_manifest, phase_cache_warm_check
from scripts.bench_report import (
    PROXY_DESCRIPTION_PREDICATE_SLUGS,
    format_summary,
)

# ---------------------------------------------------------------------------
# SQLite schema fixtures — minimal tables mirroring production schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS predicates (
    id TEXT,
    workspace_id TEXT,
    slug TEXT,
    PRIMARY KEY (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS entity_types (
    id TEXT,
    workspace_id TEXT,
    slug TEXT,
    PRIMARY KEY (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT,
    workspace_id TEXT,
    entity_type_id TEXT,
    name TEXT,
    is_deleted INTEGER DEFAULT 0,
    created_at TEXT,
    PRIMARY KEY (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS extraction_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT,
    status TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    tokens_cached INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    cortex_cost_usd REAL DEFAULT 0,
    crystallizer_cost_usd REAL DEFAULT 0,
    entities_created INTEGER DEFAULT 0,
    entities_merged INTEGER DEFAULT 0,
    relations_created INTEGER DEFAULT 0,
    claims_created INTEGER DEFAULT 0,
    claims_superseded INTEGER DEFAULT 0,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    workspace_id TEXT,
    predicate_id TEXT,
    entity_id TEXT,
    extraction_run_id TEXT,
    value TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS integrator_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT,
    status TEXT,
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    entities_scanned INTEGER DEFAULT 0,
    entities_deduplicated INTEGER DEFAULT 0,
    entities_merged INTEGER DEFAULT 0,
    entities_enriched INTEGER DEFAULT 0,
    relations_created INTEGER DEFAULT 0,
    claims_updated INTEGER DEFAULT 0,
    noise_removed INTEGER DEFAULT 0,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS integrator_actions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT,
    integrator_run_id TEXT,
    action_type TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_traces (
    id TEXT PRIMARY KEY,
    workspace_id TEXT,
    event_id TEXT,
    extraction_run_id TEXT,
    integrator_run_id TEXT,
    stage TEXT,
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    created_at TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    tokens_cached INTEGER DEFAULT 0,
    cache_write_5m_tokens INTEGER DEFAULT 0,
    cache_write_1h_tokens INTEGER DEFAULT 0
);
"""


def _make_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.connect() as conn:
        for stmt in SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()
    return engine


def _uid() -> str:
    return str(uuid.uuid4())


def _ts(offset_seconds: int = 0) -> str:
    """Return an ISO timestamp offset from a fixed anchor."""
    base = datetime(2024, 7, 1, 10, 0, 0, tzinfo=UTC)
    return (base + timedelta(seconds=offset_seconds)).isoformat()


ANCHOR_DT = datetime(2024, 7, 1, 10, 0, 0, tzinfo=UTC)
BEFORE_DT = ANCHOR_DT - timedelta(hours=1)  # before the bench window


# ---------------------------------------------------------------------------
# Helper: insert rows
# ---------------------------------------------------------------------------


def _insert_extraction_run(conn, ws_id: str, run_id: str, status: str = "completed", offset: int = 0):
    conn.execute(
        text(
            "INSERT INTO extraction_runs (id, workspace_id, status, cost_usd, started_at, completed_at)"
            " VALUES (:id, :ws, :status, 0.001, :started_at, :completed_at)"
        ),
        {"id": run_id, "ws": ws_id, "status": status, "started_at": _ts(offset), "completed_at": _ts(offset + 60)},
    )


def _insert_claim(conn, ws_id: str, claim_id: str, predicate_id: str, entity_id: str, run_id: str, offset: int = 10):
    conn.execute(
        text(
            "INSERT INTO claims (id, workspace_id, predicate_id, entity_id, extraction_run_id, value, created_at)"
            " VALUES (:id, :ws, :pred, :entity, :run, 'v', :created_at)"
        ),
        {
            "id": claim_id,
            "ws": ws_id,
            "pred": predicate_id,
            "entity": entity_id,
            "run": run_id,
            "created_at": _ts(offset),
        },
    )


def _insert_predicate(conn, ws_id: str, pred_id: str, slug: str):
    conn.execute(
        text("INSERT INTO predicates (id, workspace_id, slug) VALUES (:id, :ws, :slug)"),
        {"id": pred_id, "ws": ws_id, "slug": slug},
    )


def _insert_entity(conn, ws_id: str, entity_id: str, offset: int = 0):
    conn.execute(
        text(
            "INSERT INTO entities (id, workspace_id, name, is_deleted, created_at)"
            " VALUES (:id, :ws, 'E', 0, :created_at)"
        ),
        {"id": entity_id, "ws": ws_id, "created_at": _ts(offset)},
    )


def _insert_integrator_run(conn, ws_id: str, run_id: str, status: str = "completed", offset: int = 120):
    conn.execute(
        text(
            "INSERT INTO integrator_runs (id, workspace_id, status, cost_usd, started_at)"
            " VALUES (:id, :ws, :status, 0.005, :started_at)"
        ),
        {"id": run_id, "ws": ws_id, "status": status, "started_at": _ts(offset)},
    )


def _insert_integrator_action(
    conn, ws_id: str, action_id: str, run_id: str, action_type: str = "merge", offset: int = 130
):
    conn.execute(
        text(
            "INSERT INTO integrator_actions (id, workspace_id, integrator_run_id, action_type, created_at)"
            " VALUES (:id, :ws, :run, :atype, :created_at)"
        ),
        {"id": action_id, "ws": ws_id, "run": run_id, "atype": action_type, "created_at": _ts(offset)},
    )


def _insert_pipeline_trace(
    conn,
    ws_id: str,
    trace_id: str,
    run_id: str,
    stage: str,
    duration_ms: int,
    offset: int = 30,
    tokens_in: int = 0,
    tokens_cached: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    integrator_run_id: str | None = None,
):
    conn.execute(
        text(
            "INSERT INTO pipeline_traces"
            " (id, workspace_id, extraction_run_id, integrator_run_id, stage, duration_ms, cost_usd, created_at,"
            "  tokens_in, tokens_cached, cache_write_5m_tokens, cache_write_1h_tokens)"
            " VALUES (:id, :ws, :run, :int_run, :stage, :dur, 0.001, :created_at,"
            "         :tokens_in, :tokens_cached, :cache_write_5m, :cache_write_1h)"
        ),
        {
            "id": trace_id,
            "ws": ws_id,
            "run": run_id,
            "int_run": integrator_run_id,
            "stage": stage,
            "dur": duration_ms,
            "created_at": _ts(offset),
            "tokens_in": tokens_in,
            "tokens_cached": tokens_cached,
            "cache_write_5m": cache_write_5m_tokens,
            "cache_write_1h": cache_write_1h_tokens,
        },
    )


# ---------------------------------------------------------------------------
# Test: empty workspace (spec edge case #11)
# ---------------------------------------------------------------------------


def test_empty_workspace_result_field():
    """Edge case #11: no extraction runs → result='empty_workspace' in manifest."""
    engine = _make_engine()
    ws_id = _uid()

    with engine.connect() as conn:
        data, _summary_md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert data["result"] == "empty_workspace"


def test_empty_workspace_empty_json_dumps():
    """Edge case #11: all JSON dump lists are empty when no runs exist."""
    engine = _make_engine()
    ws_id = _uid()

    with engine.connect() as conn:
        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert data["extraction_runs"] == []
    assert data["integrator_runs"] == []
    assert data["pipeline_traces"] == []


def test_empty_workspace_summary_contains_no_events():
    """Edge case #11: summary.md says 'no events processed'."""
    engine = _make_engine()
    ws_id = _uid()

    with engine.connect() as conn:
        _, summary_md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert "no events processed" in summary_md.lower()


def test_empty_workspace_quality_proxies_none():
    """Edge case #11: quality proxies are None/zero in empty workspace."""
    engine = _make_engine()
    ws_id = _uid()

    with engine.connect() as conn:
        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    qp = data["quality_proxies"]
    assert qp["description_rate"] is None
    assert qp["claims_per_entity"] is None
    assert qp["claims_per_event_stddev"] is None
    assert qp["dedup_actions"] == 0
    assert qp["run_failure_count"] == 0


# ---------------------------------------------------------------------------
# Test: return types and markdown shape
# ---------------------------------------------------------------------------


def test_format_summary_returns_tuple():
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        conn.commit()
        result = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert isinstance(result, tuple)
    assert len(result) == 2
    data, md = result
    assert isinstance(data, dict)
    assert isinstance(md, str)


def test_markdown_has_required_sections():
    """Summary must contain Identity, Latency, Token Usage, Cost, Quality Proxies, Run Health."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        conn.commit()
        _, md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert "## Identity" in md
    assert "## Latency" in md
    assert "## Token Usage" in md
    assert "## Cost" in md
    assert "## Quality Proxies" in md
    assert "## Run Health" in md


def test_markdown_has_workspace_id():
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        conn.commit()
        _, md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert ws_id in md


# ---------------------------------------------------------------------------
# Test: quality proxy formulas
# ---------------------------------------------------------------------------


def test_description_rate_formula():
    """description_rate = description_claims / total_claims."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()
    entity_id = _uid()
    pred_desc_id = _uid()
    pred_other_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        _insert_entity(conn, ws_id, entity_id)
        _insert_predicate(conn, ws_id, pred_desc_id, "description")
        _insert_predicate(conn, ws_id, pred_other_id, "status")
        # 1 description claim, 3 other claims → rate = 0.25
        _insert_claim(conn, ws_id, _uid(), pred_desc_id, entity_id, run_id, offset=10)
        _insert_claim(conn, ws_id, _uid(), pred_other_id, entity_id, run_id, offset=11)
        _insert_claim(conn, ws_id, _uid(), pred_other_id, entity_id, run_id, offset=12)
        _insert_claim(conn, ws_id, _uid(), pred_other_id, entity_id, run_id, offset=13)
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert data["quality_proxies"]["description_rate"] == pytest.approx(0.25, abs=0.001)


def test_description_rate_zero_when_no_description_claims():
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()
    entity_id = _uid()
    pred_other_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        _insert_entity(conn, ws_id, entity_id)
        _insert_predicate(conn, ws_id, pred_other_id, "status")
        _insert_claim(conn, ws_id, _uid(), pred_other_id, entity_id, run_id, offset=10)
        _insert_claim(conn, ws_id, _uid(), pred_other_id, entity_id, run_id, offset=11)
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert data["quality_proxies"]["description_rate"] == pytest.approx(0.0, abs=0.001)


def test_claims_per_entity_formula():
    """claims_per_entity = total_claims / total_entities."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()
    entity1_id = _uid()
    entity2_id = _uid()
    pred_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        _insert_entity(conn, ws_id, entity1_id)
        _insert_entity(conn, ws_id, entity2_id)
        _insert_predicate(conn, ws_id, pred_id, "status")
        # 6 claims / 2 entities = 3.0
        for _ in range(6):
            _insert_claim(conn, ws_id, _uid(), pred_id, entity1_id, run_id, offset=10)
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert data["quality_proxies"]["claims_per_entity"] == pytest.approx(3.0, abs=0.001)


def test_claims_per_event_stddev_formula():
    """claims_per_event_stddev = population std-dev of claims per extraction_run."""
    engine = _make_engine()
    ws_id = _uid()
    run1_id = _uid()
    run2_id = _uid()
    run3_id = _uid()
    pred_id = _uid()
    entity_id = _uid()

    claim_counts = [2, 4, 6]  # std-dev = pstdev([2,4,6]) ≈ 1.6329...

    with engine.connect() as conn:
        _insert_entity(conn, ws_id, entity_id)
        _insert_predicate(conn, ws_id, pred_id, "status")
        for run_id, count in zip([run1_id, run2_id, run3_id], claim_counts, strict=True):
            _insert_extraction_run(conn, ws_id, run_id)
            for i in range(count):
                _insert_claim(conn, ws_id, _uid(), pred_id, entity_id, run_id, offset=10 + i)
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    expected_stddev = statistics.pstdev(claim_counts)
    assert data["quality_proxies"]["claims_per_event_stddev"] == pytest.approx(expected_stddev, abs=0.001)


def test_dedup_actions_count():
    """dedup_actions = count of merge integrator_actions in window."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()
    int_run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        _insert_integrator_run(conn, ws_id, int_run_id)
        # 3 merge actions
        _insert_integrator_action(conn, ws_id, _uid(), int_run_id, "merge")
        _insert_integrator_action(conn, ws_id, _uid(), int_run_id, "merge")
        _insert_integrator_action(conn, ws_id, _uid(), int_run_id, "merge")
        # 1 non-merge action (should not be counted)
        _insert_integrator_action(conn, ws_id, _uid(), int_run_id, "enrich")
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert data["quality_proxies"]["dedup_actions"] == 3


def test_run_failure_count():
    """run_failure_count = count of failed extraction_runs in window."""
    engine = _make_engine()
    ws_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, _uid(), status="failed")
        _insert_extraction_run(conn, ws_id, _uid(), status="failed")
        _insert_extraction_run(conn, ws_id, _uid(), status="completed")
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert data["quality_proxies"]["run_failure_count"] == 2


# ---------------------------------------------------------------------------
# Test: workspace_id scoping
# ---------------------------------------------------------------------------


def test_workspace_scoping_excludes_other_workspace():
    """Queries must be scoped to the bench workspace — other workspaces not counted."""
    engine = _make_engine()
    ws_bench = _uid()
    ws_other = _uid()
    run_bench = _uid()
    run_other = _uid()
    pred_id = _uid()
    entity_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_bench, run_bench)
        _insert_extraction_run(conn, ws_other, run_other)
        _insert_entity(conn, ws_bench, entity_id)
        _insert_predicate(conn, ws_bench, pred_id, "status")
        # 3 claims in bench workspace, 10 in other workspace
        for _ in range(3):
            _insert_claim(conn, ws_bench, _uid(), pred_id, entity_id, run_bench, offset=10)
        # other workspace claims won't have matching predicate+entity in bench ws
        conn.commit()

        data_bench, _ = format_summary(conn, uuid.UUID(ws_bench), ANCHOR_DT)
        data_other, _ = format_summary(conn, uuid.UUID(ws_other), ANCHOR_DT)

    # bench workspace has 1 entity, 3 claims → 3.0
    assert data_bench["quality_proxies"]["claims_per_entity"] == pytest.approx(3.0, abs=0.001)
    # other workspace has no entities (we didn't insert) → None
    assert data_other["quality_proxies"]["claims_per_entity"] is None


# ---------------------------------------------------------------------------
# Test: started_at timestamp filter
# ---------------------------------------------------------------------------


def test_pipeline_traces_filter_excludes_old_traces():
    """pipeline_traces with created_at before started_at should not be returned.

    extraction_runs.started_at is nullable (never set in practice), so temporal
    scoping for extraction_runs was dropped — workspace isolation suffices.
    pipeline_traces.created_at IS always populated, so temporal filter is kept there.
    """
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()
    old_trace_id = _uid()
    new_trace_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        # Old trace: created_at 1 hour before ANCHOR_DT (before the bench window)
        conn.execute(
            text(
                "INSERT INTO pipeline_traces"
                " (id, workspace_id, extraction_run_id, stage, duration_ms, cost_usd, created_at)"
                " VALUES (:id, :ws, :run, 'cortex', 100, 0.001, :ts)"
            ),
            {"id": old_trace_id, "ws": ws_id, "run": run_id, "ts": BEFORE_DT.isoformat()},
        )
        # New trace: created_at at ANCHOR_DT + 30 seconds (inside window)
        conn.execute(
            text(
                "INSERT INTO pipeline_traces"
                " (id, workspace_id, extraction_run_id, stage, duration_ms, cost_usd, created_at)"
                " VALUES (:id, :ws, :run, 'cortex', 150, 0.001, :ts)"
            ),
            {"id": new_trace_id, "ws": ws_id, "run": run_id, "ts": _ts(30)},
        )
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    # Only the new trace should be returned (old one is before the bench window)
    assert len(data["pipeline_traces"]) == 1
    assert data["pipeline_traces"][0]["id"] == new_trace_id


# ---------------------------------------------------------------------------
# Test: secrets policy
# ---------------------------------------------------------------------------


def test_no_api_key_in_manifest_dict():
    """Manifest dict must not contain any 'ak_' prefixed string as a value."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        conn.commit()
        data, md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    manifest_bytes = json.dumps(data).encode()
    summary_bytes = md.encode()

    # grep for ak_ prefix — must not appear in any output bytes
    assert b"ak_" not in manifest_bytes, "API key prefix 'ak_' found in manifest data"
    assert b"ak_" not in summary_bytes, "API key prefix 'ak_' found in summary markdown"


def test_no_api_key_in_empty_workspace_output():
    """Secrets policy also applies to empty workspace path."""
    engine = _make_engine()
    ws_id = _uid()

    with engine.connect() as conn:
        data, md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    manifest_bytes = json.dumps(data).encode()
    summary_bytes = md.encode()
    assert b"ak_" not in manifest_bytes
    assert b"ak_" not in summary_bytes


# ---------------------------------------------------------------------------
# Test: pipeline_traces JSON dump (per-call rows)
# ---------------------------------------------------------------------------


def test_pipeline_traces_per_call_rows():
    """pipeline_traces must be per-call rows, not run-level rollups."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()
    trace1_id = _uid()
    trace2_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        _insert_pipeline_trace(conn, ws_id, trace1_id, run_id, "cortex", 100, offset=30)
        _insert_pipeline_trace(conn, ws_id, trace2_id, run_id, "crystallizer", 250, offset=35)
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    # Should have 2 individual rows, not a single rollup
    assert len(data["pipeline_traces"]) == 2
    trace_ids = {t["id"] for t in data["pipeline_traces"]}
    assert trace1_id in trace_ids
    assert trace2_id in trace_ids


# ---------------------------------------------------------------------------
# Test: latency p50/p95 with sufficient samples
# ---------------------------------------------------------------------------


def test_latency_na_for_insufficient_samples():
    """Stages with < 5 samples report 'n/a' for p50/p95."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        # Only 3 traces for cortex — below the 5-sample threshold
        for i in range(3):
            _insert_pipeline_trace(conn, ws_id, _uid(), run_id, "cortex", 100 + i * 10, offset=30 + i)
        conn.commit()

        _data, md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    # n/a should appear in the markdown (latency table)
    assert "n/a" in md


# ---------------------------------------------------------------------------
# Test: PROXY_DESCRIPTION_PREDICATE_SLUGS constant is stable
# ---------------------------------------------------------------------------


def test_proxy_description_predicate_slugs_contains_description():
    """The constant must contain 'description' so future slug renames can be tracked."""
    assert "description" in PROXY_DESCRIPTION_PREDICATE_SLUGS


# ---------------------------------------------------------------------------
# Test: manifest data is JSON-serialisable
# ---------------------------------------------------------------------------


def test_manifest_data_is_json_serialisable():
    """Manifest dict must be fully JSON serialisable (no UUID or datetime objects)."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        conn.commit()
        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    # Must not raise
    serialized = json.dumps(data)
    assert len(serialized) > 10


# ---------------------------------------------------------------------------
# Test: _build_manifest secrets policy (I6)
# Verifies that bench.py's manifest construction never leaks raw env values
# even when sentinel "ak_"-prefixed values are injected into model env vars.
# ---------------------------------------------------------------------------


def test_build_manifest_no_secrets_in_env_vars(monkeypatch):
    """Manifest construction must not leak raw env values (charter §11).

    Even if an operator uses 'ak_'-prefixed values in model config env vars,
    _build_manifest must only emit 'set'/'unset' — never the raw value.
    """
    # Inject sentinel values into every env var that could appear in manifest
    secret_sentinel = "ak_test_secret_DO_NOT_LEAK_xxxx"
    model_sentinel = "ak_test_secret_DO_NOT_LEAK_yyyy"

    monkeypatch.setenv("ANTHROPIC_API_KEY", secret_sentinel)
    monkeypatch.setenv("CORTEX_CLASSIFIER_MODEL", model_sentinel)
    monkeypatch.setenv("CRYSTALLIZER_MODEL", model_sentinel)
    monkeypatch.setenv("INTEGRATOR_MODEL", model_sentinel)
    monkeypatch.setenv("ASK_MODEL", model_sentinel)
    monkeypatch.setenv("TREE_BRIEFING_MODEL", model_sentinel)

    fixture_path = FIXTURES_DIR / "small.jsonl"
    fixture_meta = {
        "name": "small",
        "path": "tests/fixtures/bench/small.jsonl",
        "file_hash": "abc123",
        "event_count": 5,
    }
    ts_started = ANCHOR_DT
    ts_completed = ANCHOR_DT + timedelta(seconds=60)

    manifest = _build_manifest(
        fixture_path=fixture_path,
        fixture_name="small",
        fixture_meta=fixture_meta,
        git_sha="abc1234",
        ts_started=ts_started,
        ts_completed=ts_completed,
        exit_code=0,
        exit_phase="complete",
        args_fixture="small",
        args_keep=False,
        args_reuse=False,
        args_timeout_seconds=600,
    )

    manifest_bytes = json.dumps(manifest).encode()

    # Neither the API key sentinel nor the model sentinel must appear anywhere
    assert b"ak_test_secret" not in manifest_bytes, "Secret sentinel 'ak_test_secret' found in manifest output"
    assert b"DO_NOT_LEAK" not in manifest_bytes, "Leak sentinel 'DO_NOT_LEAK' found in manifest output"


def test_build_manifest_model_versions_masked(monkeypatch):
    """model_versions in manifest must be set/unset, never raw env values."""
    monkeypatch.setenv("CORTEX_CLASSIFIER_MODEL", "claude-haiku-secret-internal")
    monkeypatch.setenv("CRYSTALLIZER_MODEL", "claude-sonnet-special")
    monkeypatch.delenv("INTEGRATOR_MODEL", raising=False)

    fixture_path = FIXTURES_DIR / "small.jsonl"
    fixture_meta = {"name": "small", "path": "tests/fixtures/bench/small.jsonl", "file_hash": "x", "event_count": 5}

    manifest = _build_manifest(
        fixture_path=fixture_path,
        fixture_name="small",
        fixture_meta=fixture_meta,
        git_sha="abc1234",
        ts_started=ANCHOR_DT,
        ts_completed=ANCHOR_DT + timedelta(seconds=60),
        exit_code=0,
        exit_phase="complete",
        args_fixture="small",
        args_keep=False,
        args_reuse=False,
        args_timeout_seconds=600,
    )

    mv = manifest["model_versions"]
    # Set vars must show "set", unset must show "unset"
    assert mv["CORTEX_CLASSIFIER_MODEL"] == "set"
    assert mv["CRYSTALLIZER_MODEL"] == "set"
    assert mv["INTEGRATOR_MODEL"] == "unset"
    # Raw model strings must not appear
    assert "claude-haiku-secret-internal" not in json.dumps(mv)
    assert "claude-sonnet-special" not in json.dumps(mv)


def test_build_manifest_env_summary_masked(monkeypatch):
    """env_summary in manifest must only contain set/unset, never raw key values."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-realkey-DO_NOT_LEAK")

    fixture_path = FIXTURES_DIR / "small.jsonl"
    fixture_meta = {"name": "small", "path": "tests/fixtures/bench/small.jsonl", "file_hash": "x", "event_count": 5}

    manifest = _build_manifest(
        fixture_path=fixture_path,
        fixture_name="small",
        fixture_meta=fixture_meta,
        git_sha="abc1234",
        ts_started=ANCHOR_DT,
        ts_completed=ANCHOR_DT + timedelta(seconds=60),
        exit_code=0,
        exit_phase="complete",
        args_fixture="small",
        args_keep=False,
        args_reuse=False,
        args_timeout_seconds=600,
    )

    env_sum = manifest["env_summary"]
    assert env_sum["ANTHROPIC_API_KEY"] == "set"
    # The raw key value must not appear
    manifest_bytes = json.dumps(manifest).encode()
    assert b"sk-ant-api03" not in manifest_bytes
    assert b"DO_NOT_LEAK" not in manifest_bytes


# ---------------------------------------------------------------------------
# Test: cache_hit_ratio_per_stage (S3)
# ---------------------------------------------------------------------------


def test_cache_hit_ratio_per_stage_computed_from_granular_columns():
    """cache_hit_ratio_per_stage = tokens_cached / total_input, aggregated per stage."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        # cortex trace: tokens_in=1000, tokens_cached=500 → ratio = 500/1500 ≈ 0.3333
        _insert_pipeline_trace(
            conn,
            ws_id,
            _uid(),
            run_id,
            "cortex",
            100,
            offset=30,
            tokens_in=1000,
            tokens_cached=500,
        )
        conn.commit()

        data, _md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    ratios = data["cache_hit_ratio_per_stage"]
    assert "cortex" in ratios
    assert ratios["cortex"] == pytest.approx(500 / 1500, abs=0.001)


def test_cache_hit_ratio_per_stage_na_when_no_granular_data():
    """Stages with total_input == 0 (no granular data) return None in the manifest."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        # trace with all-zero granular columns (legacy pre-migration-009 row)
        _insert_pipeline_trace(
            conn,
            ws_id,
            _uid(),
            run_id,
            "crystallizer",
            200,
            offset=35,
            tokens_in=0,
            tokens_cached=0,
        )
        conn.commit()

        data, _md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    ratios = data["cache_hit_ratio_per_stage"]
    assert "crystallizer" in ratios
    assert ratios["crystallizer"] is None


def test_cache_hit_ratio_per_stage_in_markdown():
    """cache_hit_ratio column in summary.md shows computed value, not 'n/a' when data exists."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        # 2000 total_input, 1000 cached → 0.50
        _insert_pipeline_trace(
            conn,
            ws_id,
            _uid(),
            run_id,
            "cortex",
            100,
            offset=30,
            tokens_in=1000,
            tokens_cached=1000,
        )
        conn.commit()

        _data, md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    # Should contain "0.50" (2 sig figs) in the token usage table
    assert "0.50" in md


def test_cache_hit_ratio_per_stage_na_in_markdown_for_empty_stages():
    """Stages without granular data show 'n/a' in the token usage table."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        _insert_pipeline_trace(
            conn,
            ws_id,
            _uid(),
            run_id,
            "crystallizer",
            200,
            offset=35,
            tokens_in=0,
            tokens_cached=0,
        )
        conn.commit()

        _data, md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert "n/a" in md


def test_cache_hit_ratio_per_stage_empty_when_no_traces():
    """Empty workspace returns empty cache_hit_ratio_per_stage dict."""
    engine = _make_engine()
    ws_id = _uid()

    with engine.connect() as conn:
        data, _md = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert data["cache_hit_ratio_per_stage"] == {}


def test_cache_hit_ratio_per_stage_aggregates_multiple_traces():
    """Multiple traces for the same stage are aggregated before computing the ratio."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        # Trace 1: tokens_in=500, tokens_cached=100 → contributes 600 total_input
        _insert_pipeline_trace(conn, ws_id, _uid(), run_id, "cortex", 100, offset=30, tokens_in=500, tokens_cached=100)
        # Trace 2: tokens_in=500, tokens_cached=300 → contributes 800 total_input
        _insert_pipeline_trace(conn, ws_id, _uid(), run_id, "cortex", 120, offset=31, tokens_in=500, tokens_cached=300)
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    # Aggregated: tokens_cached=400, total_input=1400 → ratio=400/1400≈0.2857
    ratios = data["cache_hit_ratio_per_stage"]
    assert "cortex" in ratios
    assert ratios["cortex"] == pytest.approx(400 / 1400, abs=0.001)


# ---------------------------------------------------------------------------
# Test: --cache-warm-check exit code behavior
# ---------------------------------------------------------------------------


def _make_bench_args(**kwargs):
    """Build a minimal argparse.Namespace for bench tests."""
    import argparse

    defaults = {
        "fixture": "small",
        "keep": False,
        "reuse": False,
        "timeout_seconds": 600,
        "cache_warm_check": True,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_cache_warm_check_exit_7_when_ratio_below_threshold(monkeypatch):
    """phase_cache_warm_check returns EXIT_CACHE_WARM_FAIL (7) when cortex ratio < 0.5."""
    args = _make_bench_args()

    # Mock _get_cortex_cache_hit_ratio to return a ratio below threshold
    import scripts.bench as bench_module

    monkeypatch.setattr(bench_module, "_get_cortex_cache_hit_ratio", lambda ws, ts: 0.20)

    rc = phase_cache_warm_check(
        args,
        ts_run1_started=ANCHOR_DT,
        ts_run1_completed=ANCHOR_DT + timedelta(seconds=120),
        ts_run2_started=ANCHOR_DT + timedelta(seconds=130),
        ts_run2_completed=ANCHOR_DT + timedelta(seconds=250),
        workspace_id=_uid(),
    )

    assert rc == EXIT_CACHE_WARM_FAIL


def test_cache_warm_check_exit_0_when_ratio_above_threshold(monkeypatch):
    """phase_cache_warm_check returns EXIT_SUCCESS (0) when cortex ratio > 0.5."""
    args = _make_bench_args()

    import scripts.bench as bench_module

    monkeypatch.setattr(bench_module, "_get_cortex_cache_hit_ratio", lambda ws, ts: 0.75)

    rc = phase_cache_warm_check(
        args,
        ts_run1_started=ANCHOR_DT,
        ts_run1_completed=ANCHOR_DT + timedelta(seconds=120),
        ts_run2_started=ANCHOR_DT + timedelta(seconds=130),
        ts_run2_completed=ANCHOR_DT + timedelta(seconds=250),
        workspace_id=_uid(),
    )

    assert rc == EXIT_SUCCESS


def test_cache_warm_check_exit_7_when_ratio_exactly_threshold(monkeypatch):
    """Ratio exactly equal to threshold (0.5) must NOT pass — must be strictly greater than."""
    args = _make_bench_args()

    import scripts.bench as bench_module

    monkeypatch.setattr(bench_module, "_get_cortex_cache_hit_ratio", lambda ws, ts: 0.5)

    rc = phase_cache_warm_check(
        args,
        ts_run1_started=ANCHOR_DT,
        ts_run1_completed=ANCHOR_DT + timedelta(seconds=120),
        ts_run2_started=ANCHOR_DT + timedelta(seconds=130),
        ts_run2_completed=ANCHOR_DT + timedelta(seconds=250),
        workspace_id=_uid(),
    )

    assert rc == EXIT_CACHE_WARM_FAIL


def test_cache_warm_check_exit_7_when_ratio_none(monkeypatch):
    """When ratio is None (no cortex traces), treat as 0.0 → exit 7."""
    args = _make_bench_args()

    import scripts.bench as bench_module

    monkeypatch.setattr(bench_module, "_get_cortex_cache_hit_ratio", lambda ws, ts: None)

    rc = phase_cache_warm_check(
        args,
        ts_run1_started=ANCHOR_DT,
        ts_run1_completed=ANCHOR_DT + timedelta(seconds=120),
        ts_run2_started=ANCHOR_DT + timedelta(seconds=130),
        ts_run2_completed=ANCHOR_DT + timedelta(seconds=250),
        workspace_id=_uid(),
    )

    assert rc == EXIT_CACHE_WARM_FAIL


def test_cache_warm_check_exit_code_7_value():
    """EXIT_CACHE_WARM_FAIL must equal 7."""
    assert EXIT_CACHE_WARM_FAIL == 7


def test_cache_warm_check_flag_in_help():
    """--cache-warm-check flag must be visible in bench.py --help."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/bench.py", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "--cache-warm-check" in result.stdout


# ---------------------------------------------------------------------------
# Test: integrator_run_id in pipeline_traces SELECT (F2 regression)
# ---------------------------------------------------------------------------


def test_pipeline_traces_includes_integrator_run_id():
    """pipeline_traces rows must expose integrator_run_id in manifest data.

    Regression for the missing integrator_run_id in _get_pipeline_traces SELECT:
    integrator-scoped traces (event_id=NULL, extraction_run_id=NULL) require
    integrator_run_id to be the only useful parent-scope identifier.
    """
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()
    int_run_id = _uid()
    trace_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        _insert_integrator_run(conn, ws_id, int_run_id)
        _insert_pipeline_trace(
            conn,
            ws_id,
            trace_id,
            run_id,
            "integrator:dedup",
            300,
            offset=40,
            integrator_run_id=int_run_id,
        )
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert len(data["pipeline_traces"]) == 1
    trace = data["pipeline_traces"][0]
    assert "integrator_run_id" in trace, "integrator_run_id missing from pipeline_traces row"
    assert trace["integrator_run_id"] == int_run_id


def test_pipeline_traces_integrator_run_id_null_when_not_set():
    """integrator_run_id must be None/null in traces without an integrator parent."""
    engine = _make_engine()
    ws_id = _uid()
    run_id = _uid()
    trace_id = _uid()

    with engine.connect() as conn:
        _insert_extraction_run(conn, ws_id, run_id)
        # No integrator_run_id supplied → defaults to NULL
        _insert_pipeline_trace(conn, ws_id, trace_id, run_id, "cortex", 100, offset=30)
        conn.commit()

        data, _ = format_summary(conn, uuid.UUID(ws_id), ANCHOR_DT)

    assert len(data["pipeline_traces"]) == 1
    trace = data["pipeline_traces"][0]
    assert "integrator_run_id" in trace
    assert trace["integrator_run_id"] is None
