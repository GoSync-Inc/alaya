"""Bench report: pure DB-query module for the Alaya benchmark harness.

Exposes:
    format_summary(conn, workspace_id, started_at) -> tuple[dict, str]

The function queries the database for extraction and integration run data,
computes quality proxies and run health metrics, and returns:
  - A dict of manifest data (quality proxies, extraction_runs, integrator_runs,
    pipeline_traces as JSON-serialisable lists, plus empty_workspace indicator).
  - A Markdown-formatted summary string.

This module has NO docker dependency and can be used standalone to re-generate
reports from existing bench data:

    from sqlalchemy import create_engine
    engine = create_engine("postgresql+psycopg2://...")
    with engine.connect() as conn:
        data, md = format_summary(conn, workspace_id=uuid, started_at=datetime(...))

Security: this module NEVER writes API keys or secret values to any output.
"""

from __future__ import annotations

import math
import statistics
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Predicate slugs considered "descriptive" for the description_rate proxy.
# Extend this list (same PR) if predicate slugs are ever renamed or split.
PROXY_DESCRIPTION_PREDICATE_SLUGS: tuple[str, ...] = ("description",)


# ---------------------------------------------------------------------------
# Internal query helpers
# ---------------------------------------------------------------------------


def _query(conn: Connection, sql: str, **params: Any) -> list[dict[str, Any]]:
    """Execute a SQL query and return list of row dicts."""
    result = conn.execute(text(sql), params)
    cols = list(result.keys())
    return [dict(zip(cols, row, strict=True)) for row in result.fetchall()]


def _scalar(conn: Connection, sql: str, **params: Any) -> Any:
    """Execute a SQL query and return a single scalar value."""
    result = conn.execute(text(sql), params)
    row = result.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Data queries (all scoped to workspace_id; temporal filter only on
# pipeline_traces.created_at and integrator_runs.started_at where columns
# are always populated)
# ---------------------------------------------------------------------------


def _get_extraction_runs(conn: Connection, workspace_id: uuid.UUID, started_at: str) -> list[dict[str, Any]]:
    # No temporal filter: extraction_runs.started_at is nullable (never set in practice).
    # Workspace isolation is sufficient — bench creates a fresh workspace per run.
    rows = _query(
        conn,
        """
        SELECT id, workspace_id, status, tokens_in, tokens_out, tokens_cached,
               cost_usd, entities_created, entities_merged, relations_created,
               claims_created, claims_superseded, started_at, completed_at
        FROM extraction_runs
        WHERE workspace_id = :wid
        ORDER BY completed_at NULLS LAST, id
        """,
        wid=str(workspace_id),
    )
    return [_serialize_row(r) for r in rows]


def _get_integrator_runs(conn: Connection, workspace_id: uuid.UUID, started_at: str) -> list[dict[str, Any]]:
    rows = _query(
        conn,
        """
        SELECT id, workspace_id, status, tokens_used, cost_usd, duration_ms,
               entities_scanned, entities_deduplicated, entities_enriched,
               relations_created, claims_updated, noise_removed,
               started_at, completed_at
        FROM integrator_runs
        WHERE workspace_id = :wid
          AND started_at >= :started_at
        ORDER BY started_at
        """,
        wid=str(workspace_id),
        started_at=started_at,
    )
    return [_serialize_row(r) for r in rows]


def _get_pipeline_traces(conn: Connection, workspace_id: uuid.UUID, started_at: str) -> list[dict[str, Any]]:
    rows = _query(
        conn,
        """
        SELECT id, workspace_id, event_id, extraction_run_id, integrator_run_id, stage,
               tokens_used, cost_usd, duration_ms, created_at,
               tokens_in, tokens_out, tokens_cached,
               cache_write_5m_tokens, cache_write_1h_tokens
        FROM pipeline_traces
        WHERE workspace_id = :wid
          AND created_at >= :started_at
        ORDER BY created_at
        """,
        wid=str(workspace_id),
        started_at=started_at,
    )
    return [_serialize_row(r) for r in rows]


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert non-JSON-serialisable types (UUID, datetime, Decimal) to native JSON types.

    Postgres NUMERIC columns (cost_usd) come back as Decimal; convert to float for
    manifest.json serialisation.
    """
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Quality proxy queries
# ---------------------------------------------------------------------------


def _description_rate(conn: Connection, workspace_id: uuid.UUID, started_at: str) -> float | None:
    """Fraction of claims that have a description predicate."""
    slugs_list = ", ".join(f"'{s}'" for s in PROXY_DESCRIPTION_PREDICATE_SLUGS)
    total = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM l2_claims c
        JOIN extraction_runs er ON er.id = c.extraction_run_id
        WHERE c.workspace_id = :wid
        """,
        wid=str(workspace_id),
    )
    if not total:
        return None

    desc_count = _scalar(
        conn,
        f"""
        SELECT COUNT(*) FROM l2_claims c
        JOIN predicate_definitions p ON p.id = c.predicate_id AND p.workspace_id = c.workspace_id
        JOIN extraction_runs er ON er.id = c.extraction_run_id
        WHERE c.workspace_id = :wid
          AND p.slug IN ({slugs_list})
        """,
        wid=str(workspace_id),
    )
    return round((desc_count or 0) / total, 4)


def _claims_per_entity(conn: Connection, workspace_id: uuid.UUID, started_at: str) -> float | None:
    """Average claims per entity (richness proxy)."""
    claims_total = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM l2_claims c
        JOIN extraction_runs er ON er.id = c.extraction_run_id
        WHERE c.workspace_id = :wid
        """,
        wid=str(workspace_id),
    )
    entities_total = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM l1_entities
        WHERE workspace_id = :wid
          AND created_at >= :started_at
          AND is_deleted = false
        """,
        wid=str(workspace_id),
        started_at=started_at,
    )
    if not entities_total:
        return None
    return round((claims_total or 0) / entities_total, 4)


def _claims_per_event_stddev(conn: Connection, workspace_id: uuid.UUID, started_at: str) -> float | None:
    """Population std-dev of claims per event (uniformity proxy)."""
    rows = _query(
        conn,
        """
        SELECT er.id AS run_id, COUNT(c.id) AS claim_count
        FROM extraction_runs er
        LEFT JOIN l2_claims c ON c.extraction_run_id = er.id
        WHERE er.workspace_id = :wid
        GROUP BY er.id
        """,
        wid=str(workspace_id),
    )
    counts = [r["claim_count"] for r in rows]
    if len(counts) < 2:
        return None
    return round(statistics.pstdev(counts), 4)


def _dedup_actions(conn: Connection, workspace_id: uuid.UUID, started_at: str) -> int:
    """Count of merge integrator_actions scoped to bench workspace + window."""
    val = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM integrator_actions ia
        JOIN integrator_runs ir ON ir.id = ia.run_id
        WHERE ia.workspace_id = :wid
          AND ir.started_at >= :started_at
          AND ia.action_type = 'merge'
        """,
        wid=str(workspace_id),
        started_at=started_at,
    )
    return int(val or 0)


def _run_failure_count(conn: Connection, workspace_id: uuid.UUID, started_at: str) -> int:
    """Count of failed extraction runs in bench workspace + window."""
    val = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM extraction_runs
        WHERE workspace_id = :wid
          AND status = 'failed'
        """,
        wid=str(workspace_id),
    )
    return int(val or 0)


# ---------------------------------------------------------------------------
# Cache hit ratio computation from pipeline_traces
# ---------------------------------------------------------------------------


def _compute_cache_hit_ratio(traces: list[dict[str, Any]]) -> dict[str, float | None]:
    """Compute cache hit ratio per stage from pipeline traces granular columns.

    cache_hit_ratio = tokens_cached / total_input
    total_input = tokens_in + tokens_cached + cache_write_5m_tokens + cache_write_1h_tokens

    Returns dict[stage] -> ratio (float 0.0-1.0) or None if no data for stage.
    Stages with total_input == 0 (no granular data) return None.
    """
    by_stage: dict[str, dict[str, int]] = {}
    for t in traces:
        stage = t.get("stage") or "unknown"
        # Granular columns — may be missing in traces created before migration 009
        tokens_in = t.get("tokens_in") or 0
        tokens_cached = t.get("tokens_cached") or 0
        cache_write_5m = t.get("cache_write_5m_tokens") or 0
        cache_write_1h = t.get("cache_write_1h_tokens") or 0

        if stage not in by_stage:
            by_stage[stage] = {
                "tokens_cached": 0,
                "total_input": 0,
            }
        by_stage[stage]["tokens_cached"] += tokens_cached
        by_stage[stage]["total_input"] += tokens_in + tokens_cached + cache_write_5m + cache_write_1h

    result: dict[str, float | None] = {}
    for stage, agg in by_stage.items():
        total_input = agg["total_input"]
        if total_input == 0:
            result[stage] = None
        else:
            ratio = agg["tokens_cached"] / total_input
            result[stage] = round(ratio, 4)
    return result


# ---------------------------------------------------------------------------
# Latency computation from pipeline_traces
# ---------------------------------------------------------------------------


def _compute_latency(traces: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compute p50/p95 latency per stage from pipeline traces.

    Returns dict[stage] -> {p50, p95, sample_count}.
    Stages with < 5 samples report "n/a".
    """
    by_stage: dict[str, list[int]] = {}
    for t in traces:
        stage = t.get("stage") or "unknown"
        duration_ms = t.get("duration_ms")
        if duration_ms is not None and duration_ms >= 0:
            by_stage.setdefault(stage, []).append(int(duration_ms))

    result: dict[str, dict[str, Any]] = {}
    for stage, durations in by_stage.items():
        n = len(durations)
        if n < 5:
            result[stage] = {"p50": "n/a", "p95": "n/a", "sample_count": n}
        else:
            sorted_d = sorted(durations)
            p50 = _percentile(sorted_d, 50)
            p95 = _percentile(sorted_d, 95)
            result[stage] = {"p50": p50, "p95": p95, "sample_count": n}
    return result


def _percentile(sorted_values: list[int], pct: int) -> float:
    """Compute percentile using nearest-rank method."""
    n = len(sorted_values)
    idx = math.ceil(pct / 100 * n) - 1
    return float(sorted_values[max(0, min(idx, n - 1))])


# ---------------------------------------------------------------------------
# Cost aggregation
# ---------------------------------------------------------------------------


def _total_cost(extraction_runs: list[dict[str, Any]], integrator_runs: list[dict[str, Any]]) -> float:
    ext_cost = sum(r.get("cost_usd") or 0.0 for r in extraction_runs)
    int_cost = sum(r.get("cost_usd") or 0.0 for r in integrator_runs)
    return round(ext_cost + int_cost, 8)


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------


def _format_cache_hit_ratio(ratio: float | None) -> str:
    """Format a cache hit ratio for display: 2 significant figures, or 'n/a'."""
    if ratio is None:
        return "n/a"
    # 2 significant figures: e.g. 0.3333 → "0.33", 0.1 → "0.10", 1.0 → "1.0"
    return f"{ratio:.2f}"


def _format_summary_md(
    workspace_id: uuid.UUID,
    started_at: datetime,
    extraction_runs: list[dict[str, Any]],
    integrator_runs: list[dict[str, Any]],
    pipeline_traces: list[dict[str, Any]],
    quality_proxies: dict[str, Any],
    latency_by_stage: dict[str, dict[str, Any]],
    cache_hit_ratio_per_stage: dict[str, float | None],
    is_empty: bool,
) -> str:
    lines: list[str] = []

    lines.append("# Bench Summary")
    lines.append("")
    lines.append("## Identity")
    lines.append(f"- **Workspace:** `{workspace_id}`")
    lines.append(f"- **Started:** {started_at.isoformat()}")
    lines.append("")

    if is_empty:
        lines.append("## Result")
        lines.append("")
        lines.append("No events processed in this bench window (empty workspace).")
        lines.append("")
        return "\n".join(lines)

    # Latency
    lines.append("## Latency (p50 / p95 per stage)")
    lines.append("")
    lines.append("| Stage | p50 (ms) | p95 (ms) | Samples |")
    lines.append("|-------|----------|----------|---------|")
    if latency_by_stage:
        for stage, lat in sorted(latency_by_stage.items()):
            lines.append(f"| {stage} | {lat['p50']} | {lat['p95']} | {lat['sample_count']} |")
    else:
        lines.append("| — | n/a | n/a | 0 |")
    lines.append("")

    # Tokens (per-stage totals from traces with granular cache_hit_ratio)
    lines.append("## Token Usage (per stage, from pipeline_traces)")
    lines.append("")
    lines.append("| Stage | tokens_used | cache_hit_ratio |")
    lines.append("|-------|-------------|-----------------|")
    stage_tokens: dict[str, int] = {}
    for t in pipeline_traces:
        stage = t.get("stage") or "unknown"
        stage_tokens[stage] = stage_tokens.get(stage, 0) + (t.get("tokens_used") or 0)
    if stage_tokens:
        for stage, tok in sorted(stage_tokens.items()):
            ratio_str = _format_cache_hit_ratio(cache_hit_ratio_per_stage.get(stage))
            lines.append(f"| {stage} | {tok} | {ratio_str} |")
    else:
        lines.append("| — | 0 | n/a |")
    lines.append("")

    # Cost
    total_cost = _total_cost(extraction_runs, integrator_runs)
    lines.append("## Cost")
    lines.append("")
    lines.append(f"- **Total cost:** ${total_cost:.6f}")
    ext_cost = round(sum(r.get("cost_usd") or 0.0 for r in extraction_runs), 8)
    int_cost = round(sum(r.get("cost_usd") or 0.0 for r in integrator_runs), 8)
    lines.append(f"- Extraction runs: ${ext_cost:.6f}")
    lines.append(f"- Integrator runs: ${int_cost:.6f}")
    lines.append("")

    # Quality proxies
    lines.append("## Quality Proxies")
    lines.append("")
    dr = quality_proxies.get("description_rate")
    cpe = quality_proxies.get("claims_per_entity")
    stddev = quality_proxies.get("claims_per_event_stddev")
    dedup = quality_proxies.get("dedup_actions")
    lines.append(f"- **description_rate:** {dr if dr is not None else 'n/a'}")
    lines.append(f"- **claims_per_entity:** {cpe if cpe is not None else 'n/a'}")
    lines.append(f"- **claims_per_event_stddev:** {stddev if stddev is not None else 'n/a'}")
    lines.append(f"- **dedup_actions:** {dedup}")
    lines.append("")

    # Run health
    lines.append("## Run Health")
    lines.append("")
    rfc = quality_proxies.get("run_failure_count", 0)
    n_extraction = len(extraction_runs)
    n_integrator = len(integrator_runs)
    lines.append(f"- **extraction_runs:** {n_extraction}")
    lines.append(f"- **integrator_runs:** {n_integrator}")
    lines.append(f"- **run_failure_count:** {rfc}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_summary(
    conn: Connection,
    workspace_id: uuid.UUID,
    started_at: datetime,
) -> tuple[dict[str, Any], str]:
    """Query DB and produce manifest data + markdown summary.

    Args:
        conn: SQLAlchemy synchronous Connection (not async).
        workspace_id: The bench workspace UUID.
        started_at: Bench start timestamp; all queries scoped to >= this time.

    Returns:
        (manifest_data, summary_md) where manifest_data is a dict of
        JSON-serialisable values to merge into the manifest.json, and
        summary_md is the formatted Markdown string.

    Edge case (spec #11): when no extraction runs exist for the workspace+window,
    returns result="empty_workspace", empty JSON lists, and a summary noting
    "no events processed".
    """
    # Convert to ISO-8601 string to ensure consistent TEXT comparison with SQLite
    # (PostgreSQL also handles ISO strings natively for timestamptz comparisons).
    started_at_str = started_at.isoformat()

    extraction_runs = _get_extraction_runs(conn, workspace_id, started_at_str)
    integrator_runs = _get_integrator_runs(conn, workspace_id, started_at_str)
    pipeline_traces = _get_pipeline_traces(conn, workspace_id, started_at_str)

    is_empty = len(extraction_runs) == 0

    if is_empty:
        manifest_data: dict[str, Any] = {
            "result": "empty_workspace",
            "quality_proxies": {
                "description_rate": None,
                "claims_per_entity": None,
                "claims_per_event_stddev": None,
                "dedup_actions": 0,
                "run_failure_count": 0,
            },
            "extraction_runs": [],
            "integrator_runs": [],
            "pipeline_traces": [],
            "cache_hit_ratio_per_stage": {},
        }
        summary_md = _format_summary_md(
            workspace_id=workspace_id,
            started_at=started_at,
            extraction_runs=[],
            integrator_runs=[],
            pipeline_traces=[],
            quality_proxies=manifest_data["quality_proxies"],
            latency_by_stage={},
            cache_hit_ratio_per_stage={},
            is_empty=True,
        )
        return manifest_data, summary_md

    # Compute quality proxies
    quality_proxies: dict[str, Any] = {
        "description_rate": _description_rate(conn, workspace_id, started_at_str),
        "claims_per_entity": _claims_per_entity(conn, workspace_id, started_at_str),
        "claims_per_event_stddev": _claims_per_event_stddev(conn, workspace_id, started_at_str),
        "dedup_actions": _dedup_actions(conn, workspace_id, started_at_str),
        "run_failure_count": _run_failure_count(conn, workspace_id, started_at_str),
    }

    latency_by_stage = _compute_latency(pipeline_traces)
    cache_hit_ratio_per_stage = _compute_cache_hit_ratio(pipeline_traces)

    manifest_data = {
        "quality_proxies": quality_proxies,
        "extraction_runs": extraction_runs,
        "integrator_runs": integrator_runs,
        "pipeline_traces": pipeline_traces,
        "cache_hit_ratio_per_stage": cache_hit_ratio_per_stage,
    }

    summary_md = _format_summary_md(
        workspace_id=workspace_id,
        started_at=started_at,
        extraction_runs=extraction_runs,
        integrator_runs=integrator_runs,
        pipeline_traces=pipeline_traces,
        quality_proxies=quality_proxies,
        latency_by_stage=latency_by_stage,
        cache_hit_ratio_per_stage=cache_hit_ratio_per_stage,
        is_empty=False,
    )

    return manifest_data, summary_md
