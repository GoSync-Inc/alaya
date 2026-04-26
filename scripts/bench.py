"""One-command reproducible benchmark for Alaya.

Phases:
  1. preflight   — docker daemon ok, ports free, ANTHROPIC_API_KEY set
  2. up          — docker compose up (skipped with --reuse)
  3. wait        — poll /health/ready
  4. bootstrap   — create workspace + API key (key written to temp file, never echoed)
  5. ingest      — POST fixture events to /ingest/text
  6. drain       — poll extraction_runs until all terminal
  7. integrator  — POST /integrator-runs/trigger, poll until terminal
  8. report      — query DB, write bench_results/{ISO_DATE}-{git_sha}/
  9. teardown    — docker compose down -v (skipped with --keep)

Exit codes:
  0  success
  1  preflight failure
  2  health-check timeout
  3  ingest error
  4  worker drain timeout (partial artifact still written)
  5  integrator timeout (partial artifact still written)
  6  report failure

Usage:
    uv run python scripts/bench.py --fixture small
    uv run python scripts/bench.py --fixture medium --keep
    uv run python scripts/bench.py --fixture large --reuse --timeout-seconds 1200
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid as uuid_mod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# When invoked as `uv run python scripts/bench.py`, sys.path[0] is `scripts/` (script dir),
# so `from scripts.bench_ingest import ...` fails because the parent (repo root) is not on path.
# Add it here so the `scripts.*` package imports inside functions resolve correctly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BENCH_TIMEOUT_SECONDS_DEFAULT = 600
API_URL = "http://localhost:8000/api/v1"
FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "bench"
BENCH_RESULTS_DIR = Path(__file__).parent.parent / "bench_results"

FIXTURE_EVENT_COUNTS = {"small": 5, "medium": 20, "large": 50}

# Ingest throttle for large fixtures. phase_up() sets INGEST_RATE_LIMIT_PER_MINUTE=10000
# in the bench compose stack (via docker-compose.yml env passthrough), so the 20 RPS
# cap here doesn't cause 429s. The cap also prevents accidental connection exhaustion and
# provides defense-in-depth for --reuse mode where the stack limit may differ.
INGEST_THROTTLE_THRESHOLD = 50
INGEST_THROTTLE_RPS = 20.0
# In --reuse mode the target is a dev stack with default ALAYA_INGEST_RATE_LIMIT_PER_MINUTE=30.
# Cap at 0.4 RPS (24/min) to stay safely under the 30/min default and avoid 429 cascades.
INGEST_THROTTLE_RPS_REUSE = 0.4

# Env vars allowed in env_summary (values masked to set/unset, never raw values)
ENV_SUMMARY_ALLOWLIST = (
    "ANTHROPIC_API_KEY",
    "CORTEX_CLASSIFIER_MODEL",
    "CRYSTALLIZER_MODEL",
    "INTEGRATOR_MODEL",
    "ASK_MODEL",
    "TREE_BRIEFING_MODEL",
    "INTEGRATOR_DEDUP_SHORTLIST_K",
    "INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD",
    "INTEGRATOR_DEDUP_BATCH_SIZE",
    "BENCH_TIMEOUT_SECONDS",
)

# ---------------------------------------------------------------------------
# Phase exit codes
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_PREFLIGHT = 1
EXIT_HEALTH_TIMEOUT = 2
EXIT_INGEST_ERROR = 3
EXIT_DRAIN_TIMEOUT = 4
EXIT_INTEGRATOR_TIMEOUT = 5
EXIT_REPORT_FAILURE = 6
EXIT_CACHE_WARM_FAIL = 7

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ingest_rps(event_count: int, reuse: bool = False) -> float | None:
    """Return the requests-per-second rate to pass to ingest_fixture.

    In --reuse mode the target is a dev stack with the default 30/min rate limit, so
    we cap at INGEST_THROTTLE_RPS_REUSE (0.4 RPS = 24/min) regardless of fixture size.

    For the bench-managed stack (reuse=False) INGEST_RATE_LIMIT_PER_MINUTE is set to 10000,
    so we apply INGEST_THROTTLE_RPS (20 RPS) only for large fixtures (> threshold) to
    prevent connection exhaustion — small/medium fixtures get no throttle (None).
    """
    if reuse:
        return INGEST_THROTTLE_RPS_REUSE
    if event_count > INGEST_THROTTLE_THRESHOLD:
        return INGEST_THROTTLE_RPS
    return None


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[bench {ts}] {msg}", flush=True)


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _drain_budget(remaining: float) -> float:
    """Return the wall-clock budget to allocate to phase_drain.

    Drain is the long pole for large fixtures (352-1936 events). Previous value of 50%
    caused drain timeouts before the integrator phase could run. 90% gives drain ample
    time while leaving ~10% for the (fast) integrator + report + teardown phases.
    """
    return remaining * 0.9


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _env_summary() -> dict[str, str]:
    """Return allow-listed env var names with values masked to 'set' or 'unset'."""
    result: dict[str, str] = {}
    for key in ENV_SUMMARY_ALLOWLIST:
        result[key] = "set" if os.environ.get(key) else "unset"
    return result


def _docker_compose(
    args: list[str],
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------


def phase_preflight() -> int:
    """Check docker, ports, and required env vars."""
    _log("Phase 1: preflight")

    # Docker daemon
    result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        _log("FAIL: Docker daemon is not running. Start Docker and retry.")
        return EXIT_PREFLIGHT

    # Required ports
    for port in (5432, 6379, 8000):
        if not _check_port_free(port):
            _log(f"FAIL: Port {port} is already in use. Free it before running bench.")
            return EXIT_PREFLIGHT

    # Required env var
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _log("FAIL: ANTHROPIC_API_KEY is not set. Export it and retry.")
        return EXIT_PREFLIGHT

    _log("Preflight OK")
    return EXIT_SUCCESS


def phase_preflight_reuse() -> int:
    """Lighter preflight for --reuse.

    Checks docker daemon and ANTHROPIC_API_KEY, then does a 1-second TCP probe to the
    API port (8000). If the port is not reachable, the stack is not running and the bench
    will hang waiting for health — fail fast instead.
    """
    _log("Phase 1: preflight (reuse mode)")

    result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        _log("FAIL: Docker daemon is not running.")
        return EXIT_PREFLIGHT

    if not os.environ.get("ANTHROPIC_API_KEY"):
        _log("FAIL: ANTHROPIC_API_KEY is not set.")
        return EXIT_PREFLIGHT

    # Fast-fail if the API port is not reachable — avoids long health-wait timeouts.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        if s.connect_ex(("127.0.0.1", 8000)) != 0:
            _log("FAIL: --reuse requires the stack to be running. Run 'just up' first.")
            return EXIT_PREFLIGHT

    _log("Preflight OK (reuse)")
    return EXIT_SUCCESS


def _scrub_host_db_redis_urls(env: dict[str, str]) -> None:
    """Remove host-side DB/Redis URL overrides from a compose environment dict.

    When a developer has sourced their host .env (which points to localhost), those
    variables leak into docker-compose via env interpolation and cause the migrations
    container to try connecting to localhost:5432 — unreachable from inside the
    docker network (OSError 111). Removing them lets compose fall back to its
    in-network defaults defined in docker-compose.yml.

    Called before the explicit in-network assignments in phase_up(), so that
    ALAYA_DATABASE_URL and ALAYA_REDIS_URL are re-added with the correct values
    immediately after this call returns.
    """
    for key in (
        "ALAYA_DATABASE_URL",
        "ALAYA_REDIS_URL",
        "DATABASE_URL",
        "REDIS_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "REDIS_HOST",
        "REDIS_PORT",
    ):
        env.pop(key, None)


def phase_up() -> int:
    """Start required docker compose services."""
    _log("Phase 2: docker compose up")
    # Override compose-host env vars to compose-internal hostnames; .env's localhost
    # values would otherwise leak into containers via compose variable interpolation.
    compose_env = os.environ.copy()
    # Scrub host-side DB/Redis URLs so compose uses its in-network defaults
    # (otherwise a developer who sourced the host .env will accidentally point
    # the bench-internal containers at localhost — which is unreachable from
    # inside the docker network and makes migrations fail with OSError 111).
    # Must run before the explicit assignments below so that the in-network
    # values are not accidentally removed by the scrub.
    _scrub_host_db_redis_urls(compose_env)
    compose_env["ALAYA_DATABASE_URL"] = "postgresql+asyncpg://alaya:alaya@postgres:5432/alaya"
    compose_env["ALAYA_REDIS_URL"] = "redis://redis:6379/0"
    compose_env["ALAYA_ENV"] = "dev"
    # Raise ingest rate limit so large realistic fixtures (~400-2000 events) don't hit
    # the default 30/min cap. This only affects the ephemeral bench stack, never production.
    compose_env["ALAYA_INGEST_RATE_LIMIT_PER_MINUTE"] = "10000"
    # Forward ALAYA_ANTHROPIC_API_KEY into the compose environment so containers (api, worker)
    # can reach the real Anthropic API. Settings uses env_prefix="ALAYA_", so the app reads
    # ALAYA_ANTHROPIC_API_KEY. The host may also export it as ANTHROPIC_API_KEY (bare form);
    # accept both. This is required when running bench from a worktree with no .env file.
    if not compose_env.get("ALAYA_ANTHROPIC_API_KEY"):
        bare_key = compose_env.get("ANTHROPIC_API_KEY", "")
        if bare_key:
            compose_env["ALAYA_ANTHROPIC_API_KEY"] = bare_key
    result = _docker_compose(
        ["up", "-d", "postgres", "redis", "migrations", "api", "worker"],
        timeout=300,
        env=compose_env,
    )
    if result.returncode != 0:
        _log(f"FAIL: docker compose up failed:\n{result.stderr}")
        return EXIT_PREFLIGHT
    _log("Services started")
    return EXIT_SUCCESS


def phase_wait(deadline: float) -> int:
    """Poll /health/ready until ok or timeout."""
    _log("Phase 3: waiting for API health")
    with httpx.Client(timeout=5.0) as client:
        while _remaining(deadline) > 0:
            try:
                r = client.get(f"{API_URL.replace('/api/v1', '')}/health/ready")
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "ok":
                        _log("API is healthy")
                        return EXIT_SUCCESS
                    _log(f"Health not ok yet: {data.get('status')}")
            except Exception:
                pass
            time.sleep(2)

    _log("FAIL: API health check timed out")
    return EXIT_HEALTH_TIMEOUT


def phase_bootstrap(deadline: float) -> tuple[int, str, str]:
    """Create a workspace and API key. Returns (exit_code, workspace_id, key_tempfile_path).

    The workspace is created via the HTTP API (requires bootstrap key).
    The bench API key is created directly via the core service layer using an async DB
    session scoped to the bench workspace — this ensures the key is bound to the correct
    workspace (the HTTP POST /api-keys endpoint ignores body.workspace_id and always uses
    the authenticated key's workspace, which is the bootstrap workspace, not the bench one).

    The API key is written to a temp file (mode 0600) and NEVER echoed.
    """
    _log("Phase 4: bootstrap workspace + API key")

    # Retrieve bootstrap key from migration logs
    result = _docker_compose(["logs", "migrations"], timeout=30)
    import re

    match = re.search(r"ak_[a-zA-Z0-9_-]+", result.stdout + result.stderr)
    if not match:
        _log("FAIL: Could not find bootstrap key in migration logs")
        return EXIT_PREFLIGHT, "", ""

    bootstrap_key = match.group(0)

    with httpx.Client(timeout=30.0) as client:
        # Create workspace via HTTP API (requires bootstrap key)
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        r = client.post(
            f"{API_URL}/workspaces",
            headers={"X-Api-Key": bootstrap_key, "Content-Type": "application/json"},
            json={"name": f"bench-{ts}", "slug": f"bench-{ts}"},
        )
        if r.status_code not in (200, 201):
            _log(f"FAIL: workspace create returned {r.status_code}: {r.text[:200]}")
            return EXIT_PREFLIGHT, "", ""

        workspace_id = r.json()["data"]["id"]
        _log(f"Workspace created: {workspace_id[:8]}…")

    # Create the bench API key directly via the core service — NOT via HTTP.
    # The POST /api-keys endpoint ignores body.workspace_id and binds the key to the
    # authenticated key's workspace (bootstrap workspace), causing all bench ingest to
    # land in the wrong workspace and report queries to return 0 rows.
    # Scope includes 'admin' so the bench key can trigger integrator runs (POST /integrator-runs/trigger).
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get(
        "ALAYA_DATABASE_URL",
        "postgresql+asyncpg://alaya:alaya@localhost:5432/alaya",
    )

    async def _create_key() -> str:
        from sqlalchemy import text as _text

        from alayaos_core.services.api_key import create_api_key

        engine = create_async_engine(db_url, future=True)
        async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with async_session_factory() as session, session.begin():
                ws_uuid = uuid_mod.UUID(workspace_id)
                validated_wid = str(ws_uuid)
                # Set RLS context so the insert is accepted by the workspace-scoped policy
                await session.execute(_text(f"SET LOCAL app.workspace_id = '{validated_wid}'"))
                api_key_obj, raw_key = await create_api_key(
                    session=session,
                    workspace_id=ws_uuid,
                    name="bench-key",
                    scopes=["read", "write", "admin"],
                )
                # Sanity check: key must be bound to bench workspace
                assert api_key_obj.workspace_id == ws_uuid, (
                    f"Key workspace mismatch: {api_key_obj.workspace_id} != {ws_uuid}"
                )
                return raw_key
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        raw_key = loop.run_until_complete(_create_key())
    except Exception as e:
        _log(f"FAIL: bench API key creation failed: {e}")
        return EXIT_PREFLIGHT, workspace_id, ""
    finally:
        loop.close()

    # Write key to temp file with restricted permissions — never echo it
    fd, key_path = tempfile.mkstemp(prefix="alaya-bench-", dir=os.environ.get("TMPDIR", "/tmp"))
    os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write(raw_key)

    _log("API key written to temp file (not echoed)")
    return EXIT_SUCCESS, workspace_id, key_path


def phase_ingest(
    fixture_path: Path,
    key_path: str,
    deadline: float,
    reuse: bool = False,
) -> tuple[int, list[dict[str, Any]]]:
    """Ingest events from fixture. Returns (exit_code, results)."""
    from scripts.bench_ingest import ingest_fixture

    _log(f"Phase 5: ingest {fixture_path.name}")
    api_key = Path(key_path).read_text().strip()

    # Count non-empty lines to decide whether to throttle.
    event_count = sum(1 for line in fixture_path.read_text().splitlines() if line.strip())
    rps = _ingest_rps(event_count, reuse=reuse)
    if rps is not None:
        _log(f"  throttling ingest to {rps} RPS ({event_count} events, reuse={reuse})")

    try:
        results = ingest_fixture(api_url=API_URL, key=api_key, fixture_path=fixture_path, rps=rps)
    except Exception as e:
        _log(f"FAIL: ingest error: {e}")
        return EXIT_INGEST_ERROR, []

    errors = [r for r in results if "error" in r]
    if errors:
        _log(f"FAIL: {len(errors)} ingest error(s): {errors[0].get('error')}")
        return EXIT_INGEST_ERROR, results

    run_ids = [r["run_id"] for r in results if "run_id" in r]
    _log(f"Ingested {len(results)} events, {len(run_ids)} extraction runs queued")
    return EXIT_SUCCESS, results


def phase_drain(
    run_ids: list[str],
    key_path: str,
    deadline: float,
) -> tuple[int, list[dict[str, Any]]]:
    """Poll extraction_runs until all terminal. Returns (exit_code, run_statuses)."""
    _log(f"Phase 6: draining {len(run_ids)} extraction runs")
    api_key = Path(key_path).read_text().strip()
    terminal = {"completed", "failed"}
    statuses: dict[str, str] = {}

    with httpx.Client(timeout=10.0) as client:
        headers = {"X-Api-Key": api_key}
        while _remaining(deadline) > 0:
            pending = [r for r in run_ids if statuses.get(r) not in terminal]
            if not pending:
                break
            for run_id in pending:
                try:
                    r = client.get(f"{API_URL}/extraction-runs/{run_id}", headers=headers)
                    if r.status_code == 200:
                        status = r.json()["data"]["status"]
                        prev = statuses.get(run_id)
                        statuses[run_id] = status
                        if status in terminal and prev not in terminal:
                            _log(f"  run {run_id[:8]} → {status}")
                except Exception:
                    pass
            # Log progress
            done = sum(1 for s in statuses.values() if s in terminal)
            _log(f"  drain: {done}/{len(run_ids)} terminal")
            if done == len(run_ids):
                break
            time.sleep(5)

    done = sum(1 for s in statuses.values() if s in terminal)
    if done < len(run_ids):
        _log(f"FAIL: drain timed out ({done}/{len(run_ids)} terminal)")
        return EXIT_DRAIN_TIMEOUT, [{"run_id": rid, "status": statuses.get(rid, "unknown")} for rid in run_ids]

    _log(f"Drain complete: {done}/{len(run_ids)} terminal")
    return EXIT_SUCCESS, [{"run_id": rid, "status": statuses.get(rid, "unknown")} for rid in run_ids]


def phase_integrator(key_path: str, workspace_id: str, deadline: float) -> tuple[int, str | None]:
    """Trigger integrator run and poll until terminal. Returns (exit_code, integrator_run_id)."""
    _log("Phase 7: integrator")
    api_key = Path(key_path).read_text().strip()

    with httpx.Client(timeout=30.0) as client:
        headers = {"X-Api-Key": api_key}

        # Trigger — endpoint returns 202 Accepted
        r = client.post(f"{API_URL}/integrator-runs/trigger", headers=headers)
        if r.status_code not in (200, 201, 202):
            _log(f"FAIL: integrator trigger returned {r.status_code}")
            return EXIT_INTEGRATOR_TIMEOUT, None

        integrator_run_id = r.json()["data"]["id"]
        _log(f"Integrator run: {integrator_run_id[:8]}…")

        # Poll
        terminal = {"completed", "failed", "skipped"}
        while _remaining(deadline) > 0:
            try:
                r = client.get(f"{API_URL}/integrator-runs/{integrator_run_id}", headers=headers)
                if r.status_code == 200:
                    status = r.json()["data"]["status"]
                    if status in terminal:
                        _log(f"Integrator run {integrator_run_id[:8]} → {status}")
                        return EXIT_SUCCESS, integrator_run_id
                    _log(f"  integrator status: {status}")
            except Exception:
                pass
            time.sleep(5)

    _log("FAIL: integrator timed out")
    return EXIT_INTEGRATOR_TIMEOUT, integrator_run_id


# Env var names whose values are masked in model_versions (same semantics as env_summary).
# Charter §11: .env content NEVER written to manifest.json — values masked to set/unset.
_MODEL_VERSION_KEYS: tuple[str, ...] = (
    "CORTEX_CLASSIFIER_MODEL",
    "CRYSTALLIZER_MODEL",
    "INTEGRATOR_MODEL",
    "ASK_MODEL",
    "TREE_BRIEFING_MODEL",
)


def _build_manifest(
    *,
    fixture_path: Path,
    fixture_name: str,
    fixture_meta: dict[str, Any],
    git_sha: str,
    ts_started: datetime,
    ts_completed: datetime,
    exit_code: int,
    exit_phase: str,
    args_fixture: str,
    args_keep: bool,
    args_reuse: bool,
    args_timeout_seconds: int,
) -> dict[str, Any]:
    """Build the base manifest dict without touching the network or DB.

    All env values are masked to 'set'/'unset' — never raw values.
    This is a pure function (no I/O) so it can be tested in isolation.
    """
    env_sum = _env_summary()
    model_versions: dict[str, str] = {k: ("set" if os.environ.get(k) else "unset") for k in _MODEL_VERSION_KEYS}

    if exit_code == EXIT_SUCCESS:
        result_type = "complete"
    elif exit_phase == "drain":
        result_type = "partial_drain"
    elif exit_phase == "integrator":
        result_type = "partial_integrator"
    elif exit_phase == "preflight":
        result_type = "preflight_failed"
    else:
        result_type = "complete"

    return {
        "schema_version": 1,
        "git_sha": git_sha,
        "ts_started": ts_started.isoformat(),
        "ts_completed": ts_completed.isoformat(),
        "fixture": fixture_meta,
        "model_versions": model_versions,
        "env_summary": env_sum,
        "command_args": {
            "fixture": args_fixture,
            "keep": args_keep,
            "reuse": args_reuse,
            "timeout_seconds": args_timeout_seconds,
        },
        "exit_code": exit_code,
        "exit_phase": exit_phase,
        "result": result_type,
    }


def phase_report(
    out_dir: Path,
    workspace_id: str,
    ts_started: datetime,
    ts_completed: datetime,
    fixture_path: Path,
    fixture_name: str,
    git_sha: str,
    exit_code: int,
    exit_phase: str,
    ingest_results: list[dict[str, Any]],
    integrator_run_id: str | None,
    args: argparse.Namespace,
) -> int:
    """Query DB and write bench output artifacts."""
    _log(f"Phase 8: report → {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fixture metadata
    fixture_meta = {
        "name": fixture_name,
        "path": str(fixture_path.relative_to(Path(__file__).parent.parent)),
        "file_hash": _sha256_file(fixture_path),
        "event_count": FIXTURE_EVENT_COUNTS.get(fixture_name, len(ingest_results)),
    }

    manifest = _build_manifest(
        fixture_path=fixture_path,
        fixture_name=fixture_name,
        fixture_meta=fixture_meta,
        git_sha=git_sha,
        ts_started=ts_started,
        ts_completed=ts_completed,
        exit_code=exit_code,
        exit_phase=exit_phase,
        args_fixture=fixture_name,
        args_keep=args.keep,
        args_reuse=args.reuse,
        args_timeout_seconds=args.timeout_seconds,
    )

    # Write manifest — security: no ak_ keys in any value
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    _log("  manifest.json written")

    # Query DB for report artifacts
    db_url = os.environ.get(
        "ALAYA_DATABASE_URL",
        "postgresql+asyncpg://alaya:alaya@localhost:5432/alaya",
    )
    try:
        from sqlalchemy import create_engine
        from sqlalchemy import text as _sql_text

        from scripts.bench_report import format_summary

        def _run_report() -> tuple[dict[str, Any], str]:
            # Use sync URL for bench_report (simpler for script context)
            sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            engine = create_engine(sync_url, future=True)
            ws_id = uuid_mod.UUID(workspace_id)
            with engine.begin() as conn:
                # Set RLS workspace context so workspace-scoped tables return rows.
                # set_config(..., false) = session-local (safe for a single-use connection).
                conn.execute(
                    _sql_text("SELECT set_config('app.workspace_id', :wid, false)"),
                    {"wid": str(ws_id)},
                )
                manifest_data, summary_text = format_summary(conn, ws_id, ts_started)
            engine.dispose()
            return manifest_data, summary_text

        report_data, summary_text = _run_report()

        # Merge report data into manifest
        manifest.update(report_data)
        manifest_path.write_text(json.dumps(manifest, indent=2))

        # Write summary.md
        (out_dir / "summary.md").write_text(summary_text)
        _log("  summary.md written")

        # Write JSON dumps
        (out_dir / "extraction_runs.json").write_text(json.dumps(report_data.get("extraction_runs", []), indent=2))
        (out_dir / "integrator_runs.json").write_text(json.dumps(report_data.get("integrator_runs", []), indent=2))
        (out_dir / "pipeline_traces.json").write_text(json.dumps(report_data.get("pipeline_traces", []), indent=2))
        _log("  JSON dumps written")

    except Exception as e:
        _log(f"FAIL: report DB query failed: {e}")
        # Write empty JSON files so manifest is consistent
        for fname in ("extraction_runs.json", "integrator_runs.json", "pipeline_traces.json"):
            (out_dir / fname).write_text("[]")
        summary_text = f"# Bench Summary\n\nReport generation failed: {e}\n"
        (out_dir / "summary.md").write_text(summary_text)
        return EXIT_REPORT_FAILURE

    _log(f"Report complete: {out_dir}")
    return EXIT_SUCCESS


def phase_teardown() -> None:
    _log("Phase 9: teardown")
    result = _docker_compose(["down", "-v"], timeout=60)
    if result.returncode != 0:
        _log(f"  teardown warning: {result.stderr[:100]}")
    else:
        _log("  services stopped and volumes removed")


# ---------------------------------------------------------------------------
# Cache warm check
# ---------------------------------------------------------------------------

_CACHE_WARM_THRESHOLD = 0.5


def _get_cortex_cache_hit_ratio(workspace_id: str, ts_started: datetime) -> float | None:
    """Query DB and return cortex stage cache_hit_ratio from the second bench run.

    Returns None when no cortex traces exist for this workspace+window.
    """
    db_url = os.environ.get(
        "ALAYA_DATABASE_URL",
        "postgresql+asyncpg://alaya:alaya@localhost:5432/alaya",
    )
    try:
        from sqlalchemy import create_engine
        from sqlalchemy import text as _sql_text

        from scripts.bench_report import format_summary

        def _query_ratio() -> float | None:
            sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            engine = create_engine(sync_url, future=True)
            ws_id = uuid_mod.UUID(workspace_id)
            with engine.begin() as conn:
                conn.execute(
                    _sql_text("SELECT set_config('app.workspace_id', :wid, false)"),
                    {"wid": str(ws_id)},
                )
                manifest_data, _ = format_summary(conn, ws_id, ts_started)
            engine.dispose()
            ratios = manifest_data.get("cache_hit_ratio_per_stage", {})
            return ratios.get("cortex")

        return _query_ratio()
    except Exception as e:
        _log(f"  cache-warm-check: DB query failed: {e}")
        return None


def phase_cache_warm_check(
    args: argparse.Namespace,
    ts_run1_started: datetime,
    ts_run1_completed: datetime,
    ts_run2_started: datetime,
    ts_run2_completed: datetime,
    workspace_id: str,
) -> int:
    """Assert that the second bench run has cortex cache_hit_ratio > 0.5.

    Returns EXIT_SUCCESS (0) on pass, EXIT_CACHE_WARM_FAIL (7) on failure.
    """
    ratio = _get_cortex_cache_hit_ratio(workspace_id, ts_run2_started)

    if ratio is None:
        ratio = 0.0

    if ratio > _CACHE_WARM_THRESHOLD:
        _log(f"cache-warm-check PASS: cortex cache_hit_ratio={ratio:.4f} > {_CACHE_WARM_THRESHOLD}")
        return EXIT_SUCCESS

    gap_seconds = (ts_run2_started - ts_run1_completed).total_seconds()
    _log(
        f"FAIL: cache-warm-check: cortex cache_hit_ratio={ratio:.4f} does not exceed threshold={_CACHE_WARM_THRESHOLD}"
    )
    _log(f"  run1_started={ts_run1_started.isoformat()}")
    _log(f"  run1_completed={ts_run1_completed.isoformat()}")
    _log(f"  run2_started={ts_run2_started.isoformat()}")
    _log(f"  run2_completed={ts_run2_completed.isoformat()}")
    _log(f"  gap_seconds={gap_seconds:.1f}")
    _log(
        "  remediation: rerun with `--keep` within 5 minutes; "
        "if persistent, check `llm.cache_miss_below_threshold` events for stage=cortex"
    )
    return EXIT_CACHE_WARM_FAIL


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-command reproducible Alaya benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fixture",
        choices=["small", "medium", "large", "realistic_3d", "realistic_14d"],
        required=True,
        help="Fixture size to use for the bench run",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Do not tear down docker compose after the run",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help=(
            "Skip docker compose up/down (stack is externally managed). "
            "Requires 'just up' to be running. Teardown is skipped — "
            "caller is responsible for shutting down the stack."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("BENCH_TIMEOUT_SECONDS", BENCH_TIMEOUT_SECONDS_DEFAULT)),
        dest="timeout_seconds",
        help=f"Global wall-clock budget in seconds (default: {BENCH_TIMEOUT_SECONDS_DEFAULT})",
    )
    parser.add_argument(
        "--cache-warm-check",
        action="store_true",
        dest="cache_warm_check",
        help=(
            "Run the bench twice (first run warms cache; second run measures). "
            "Asserts that the second-run cortex cache_hit_ratio > 0.5. "
            "On failure, exits with code 7 (EXIT_CACHE_WARM_FAIL)."
        ),
    )
    return parser


def _run_single_bench(
    args: argparse.Namespace,
    fixture_name: str,
    fixture_path: Path,
    git_sha: str,
    out_dir: Path,
    deadline: float,
    reuse: bool,
) -> tuple[int, str, datetime, datetime]:
    """Execute a single bench run (phases 4-8).

    Assumes preflight + up + wait have already been called (stack is live).
    Returns (exit_code, workspace_id, ts_started, ts_completed).
    """
    ts_started = datetime.now(UTC)
    key_path: str = ""
    workspace_id: str = ""
    ingest_results: list[dict[str, Any]] = []
    integrator_run_id: str | None = None

    try:
        # Phase 4: bootstrap
        rc, workspace_id, key_path = phase_bootstrap(deadline)
        if rc != EXIT_SUCCESS:
            return rc, "", ts_started, datetime.now(UTC)

        # Phase 5: ingest
        rc, ingest_results = phase_ingest(fixture_path, key_path, deadline, reuse=reuse)
        if rc != EXIT_SUCCESS:
            return rc, workspace_id, ts_started, datetime.now(UTC)

        # Phase 6: drain — use 90% of remaining budget (drain is the long pole;
        # integrator + report + teardown are fast and fit in the remaining 10%)
        drain_budget = _drain_budget(_remaining(deadline))
        drain_deadline = time.monotonic() + drain_budget
        run_ids = [r["run_id"] for r in ingest_results if "run_id" in r]
        rc, _ = phase_drain(run_ids, key_path, drain_deadline)
        if rc != EXIT_SUCCESS:
            ts_completed = datetime.now(UTC)
            phase_report(
                out_dir,
                workspace_id,
                ts_started,
                ts_completed,
                fixture_path,
                fixture_name,
                git_sha,
                rc,
                "drain",
                ingest_results,
                None,
                args,
            )
            return rc, workspace_id, ts_started, ts_completed

        # Phase 7: integrator
        rc, integrator_run_id = phase_integrator(key_path, workspace_id, deadline)
        if rc != EXIT_SUCCESS:
            ts_completed = datetime.now(UTC)
            phase_report(
                out_dir,
                workspace_id,
                ts_started,
                ts_completed,
                fixture_path,
                fixture_name,
                git_sha,
                rc,
                "integrator",
                ingest_results,
                integrator_run_id,
                args,
            )
            return rc, workspace_id, ts_started, ts_completed

        # Phase 8: report
        ts_completed = datetime.now(UTC)
        rc = phase_report(
            out_dir,
            workspace_id,
            ts_started,
            ts_completed,
            fixture_path,
            fixture_name,
            git_sha,
            EXIT_SUCCESS,
            "complete",
            ingest_results,
            integrator_run_id,
            args,
        )
        return rc, workspace_id, ts_started, ts_completed

    finally:
        # Clean up temp key file
        if key_path and Path(key_path).exists():
            try:
                Path(key_path).unlink()
                _log("Temp key file deleted")
            except Exception:
                pass


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ts_started = datetime.now(UTC)
    global_start = time.monotonic()
    deadline = global_start + args.timeout_seconds

    git_sha = _git_sha()
    iso_date = ts_started.strftime("%Y-%m-%d")
    out_dir = BENCH_RESULTS_DIR / f"{iso_date}-{git_sha}"

    fixture_name = args.fixture
    fixture_path = FIXTURES_DIR / f"{fixture_name}.jsonl"

    if not fixture_path.exists():
        _log(f"FAIL: Fixture not found: {fixture_path}")
        return EXIT_PREFLIGHT

    _log(f"Bench start: fixture={fixture_name} timeout={args.timeout_seconds}s")
    _log(f"Output dir: {out_dir}")

    # Track whether this bench invocation started the docker stack.
    we_started_stack: bool = False

    try:
        # Phase 1: preflight
        rc = phase_preflight_reuse() if args.reuse else phase_preflight()
        if rc != EXIT_SUCCESS:
            return rc

        # Phase 2: up
        if not args.reuse:
            rc = phase_up()
            if rc != EXIT_SUCCESS:
                return rc
            we_started_stack = True

        # Phase 3: wait
        rc = phase_wait(deadline)
        if rc != EXIT_SUCCESS:
            return rc

        if args.cache_warm_check:
            _log("cache-warm-check: starting run 1 (cache warm-up)")
            run1_out = out_dir / "run1"
            rc1, _ws1, ts1_start, ts1_end = _run_single_bench(
                args, fixture_name, fixture_path, git_sha, run1_out, deadline, reuse=True
            )
            if rc1 != EXIT_SUCCESS:
                return rc1

            _log("cache-warm-check: starting run 2 (cache measurement)")
            run2_out = out_dir / "run2"
            rc2, ws2, ts2_start, ts2_end = _run_single_bench(
                args, fixture_name, fixture_path, git_sha, run2_out, deadline, reuse=True
            )
            if rc2 != EXIT_SUCCESS:
                return rc2

            # Assert cache hit ratio > threshold for cortex stage in run 2
            return phase_cache_warm_check(
                args,
                ts_run1_started=ts1_start,
                ts_run1_completed=ts1_end,
                ts_run2_started=ts2_start,
                ts_run2_completed=ts2_end,
                workspace_id=ws2,
            )

        # Normal single-run path
        rc, _ws, _ts_start, _ts_end = _run_single_bench(
            args, fixture_name, fixture_path, git_sha, out_dir, deadline, reuse=args.reuse
        )
        return rc

    except KeyboardInterrupt:
        _log("Interrupted by user")
        return EXIT_PREFLIGHT

    finally:
        # Phase 9: teardown — only if we started the stack in this run.
        # With --reuse the stack is externally owned; with preflight failures
        # before phase_up, we_started_stack stays False and no teardown happens.
        if we_started_stack and not args.keep:
            phase_teardown()
        elif args.keep:
            _log("--keep: skipping teardown")
        elif args.reuse:
            _log("--reuse: stack externally owned, skipping teardown")


if __name__ == "__main__":
    sys.exit(main())
