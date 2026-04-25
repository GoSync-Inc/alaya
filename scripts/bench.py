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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BENCH_TIMEOUT_SECONDS_DEFAULT = 600
API_URL = "http://localhost:8000/api/v1"
FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "bench"
BENCH_RESULTS_DIR = Path(__file__).parent.parent / "bench_results"

FIXTURE_EVENT_COUNTS = {"small": 5, "medium": 20, "large": 50}

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[bench {ts}] {msg}", flush=True)


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


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


def _docker_compose(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


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
    """Lighter preflight for --reuse (skip port checks, services are already up)."""
    _log("Phase 1: preflight (reuse mode — skipping port checks)")

    result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        _log("FAIL: Docker daemon is not running.")
        return EXIT_PREFLIGHT

    if not os.environ.get("ANTHROPIC_API_KEY"):
        _log("FAIL: ANTHROPIC_API_KEY is not set.")
        return EXIT_PREFLIGHT

    _log("Preflight OK (reuse)")
    return EXIT_SUCCESS


def phase_up() -> int:
    """Start required docker compose services."""
    _log("Phase 2: docker compose up")
    result = _docker_compose(
        ["up", "-d", "postgres", "redis", "migrations", "api", "worker"],
        timeout=120,
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
        # Create workspace
        r = client.post(
            f"{API_URL}/workspaces",
            headers={"X-Api-Key": bootstrap_key, "Content-Type": "application/json"},
            json={"name": f"bench-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"},
        )
        if r.status_code not in (200, 201):
            _log(f"FAIL: workspace create returned {r.status_code}: {r.text[:200]}")
            return EXIT_PREFLIGHT, "", ""

        workspace_id = r.json()["data"]["id"]
        _log(f"Workspace created: {workspace_id[:8]}…")

        # Create API key for the workspace
        r = client.post(
            f"{API_URL}/api-keys",
            headers={"X-Api-Key": bootstrap_key, "Content-Type": "application/json"},
            json={"workspace_id": workspace_id, "name": "bench-key", "scopes": ["write"]},
        )
        if r.status_code not in (200, 201):
            _log(f"FAIL: api-key create returned {r.status_code}: {r.text[:200]}")
            return EXIT_PREFLIGHT, workspace_id, ""

        raw_key = r.json()["data"]["key"]

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
) -> tuple[int, list[dict[str, Any]]]:
    """Ingest events from fixture. Returns (exit_code, results)."""
    from scripts.bench_ingest import ingest_fixture

    _log(f"Phase 5: ingest {fixture_path.name}")
    api_key = Path(key_path).read_text().strip()

    try:
        results = ingest_fixture(api_url=API_URL, key=api_key, fixture_path=fixture_path)
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
                        statuses[run_id] = status
                        if status in terminal and run_id not in statuses:
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

        # Trigger
        r = client.post(f"{API_URL}/integrator-runs/trigger", headers=headers)
        if r.status_code not in (200, 201):
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

    # Build env_summary — NEVER include values, only set/unset status
    env_sum = _env_summary()

    # Build model_versions from env vars (values allowed — these are model names not secrets)
    model_versions = {
        "cortex_classifier_model": os.environ.get("CORTEX_CLASSIFIER_MODEL", "unset"),
        "crystallizer_model": os.environ.get("CRYSTALLIZER_MODEL", "unset"),
        "integrator_model": os.environ.get("INTEGRATOR_MODEL", "unset"),
        "ask_model": os.environ.get("ASK_MODEL", "unset"),
        "tree_briefing_model": os.environ.get("TREE_BRIEFING_MODEL", "unset"),
    }

    # Fixture metadata
    fixture_meta = {
        "name": fixture_name,
        "path": str(fixture_path.relative_to(Path(__file__).parent.parent)),
        "file_hash": _sha256_file(fixture_path),
        "event_count": FIXTURE_EVENT_COUNTS.get(fixture_name, len(ingest_results)),
    }

    # Determine result type
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

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "git_sha": git_sha,
        "ts_started": ts_started.isoformat(),
        "ts_completed": ts_completed.isoformat(),
        "fixture": fixture_meta,
        "model_versions": model_versions,
        "env_summary": env_sum,
        "command_args": {
            "fixture": fixture_name,
            "keep": args.keep,
            "reuse": args.reuse,
            "timeout_seconds": args.timeout_seconds,
        },
        "exit_code": exit_code,
        "exit_phase": exit_phase,
        "result": result_type,
    }

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
        import asyncio

        from scripts.bench_report import format_summary

        async def _run_report() -> tuple[dict[str, Any], str]:

            # Use sync URL for bench_report (simpler for script context)
            sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            from sqlalchemy import create_engine

            engine = create_engine(sync_url, future=True)
            with engine.connect() as conn:
                import uuid as uuid_mod

                ws_id = uuid_mod.UUID(workspace_id)
                manifest_data, summary_text = format_summary(conn, ws_id, ts_started)
            engine.dispose()
            return manifest_data, summary_text

        # Run synchronously since bench.py is a script
        loop = asyncio.new_event_loop()
        try:
            report_data, summary_text = loop.run_until_complete(_run_report())
        finally:
            loop.close()

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
# Main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-command reproducible Alaya benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fixture",
        choices=["small", "medium", "large"],
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
        help="Skip docker compose up (assume stack is already running)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("BENCH_TIMEOUT_SECONDS", BENCH_TIMEOUT_SECONDS_DEFAULT)),
        dest="timeout_seconds",
        help=f"Global wall-clock budget in seconds (default: {BENCH_TIMEOUT_SECONDS_DEFAULT})",
    )
    return parser


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

    key_path: str = ""
    workspace_id: str = ""
    ingest_results: list[dict[str, Any]] = []
    integrator_run_id: str | None = None

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

        # Phase 3: wait
        rc = phase_wait(deadline)
        if rc != EXIT_SUCCESS:
            return rc

        # Phase 4: bootstrap
        rc, workspace_id, key_path = phase_bootstrap(deadline)
        if rc != EXIT_SUCCESS:
            return rc

        # Phase 5: ingest
        rc, ingest_results = phase_ingest(fixture_path, key_path, deadline)
        if rc != EXIT_SUCCESS:
            return rc

        # Phase 6: drain — use 50% of remaining budget
        drain_budget = _remaining(deadline) * 0.5
        drain_deadline = time.monotonic() + drain_budget
        run_ids = [r["run_id"] for r in ingest_results if "run_id" in r]
        rc, _ = phase_drain(run_ids, key_path, drain_deadline)
        if rc != EXIT_SUCCESS:
            # Write partial artifact and exit
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
            return rc

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
            return rc

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
        return rc

    except KeyboardInterrupt:
        _log("Interrupted by user")
        return EXIT_PREFLIGHT

    finally:
        # Clean up temp key file
        if key_path and Path(key_path).exists():
            try:
                Path(key_path).unlink()
                _log("Temp key file deleted")
            except Exception:
                pass

        # Phase 9: teardown
        if not args.keep:
            phase_teardown()
        else:
            _log("--keep: skipping teardown")


if __name__ == "__main__":
    sys.exit(main())
