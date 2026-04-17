"""Ingest benchmark helper for Alaya.

POSTs a JSONL batch of events to /ingest/text, collects the returned
run_ids, and writes results to a JSON file for SQL follow-up queries.

Preconditions:
  - Alaya API server running (default: http://localhost:8000/api/v1)
  - TaskIQ worker running (processes the queued extraction jobs)
  - A valid API key created in the target workspace

Usage:
    uv run python scripts/bench_ingest.py --key ak_xxx --file path/to/events.jsonl
"""

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def _parse_occurred_at(raw: str | int | float | None) -> str | None:
    """Parse a Slack/PG-style timestamp into an ISO 8601 string, or return None."""
    if raw is None or raw == "":
        return None
    raw_str = str(raw)
    try:
        if re.fullmatch(r"\d+(\.\d+)?", raw_str):
            return datetime.fromtimestamp(float(raw_str), tz=UTC).isoformat()
        s = raw_str.replace(" ", "T")
        # Normalize bare ±HH offset (no minutes) → ±HH:00
        s = re.sub(r"([+-]\d{2})$", r"\1:00", s)
        return datetime.fromisoformat(s).isoformat()
    except Exception:
        print(f"  warn: could not parse occurred_at from {raw!r}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ingest: POST events to /ingest/text")
    parser.add_argument("--key", required=True, help="API key (ak_xxx)")
    parser.add_argument(
        "--file",
        required=True,
        help="JSONL events file (one event per line; expected keys: id, raw_text, optionally ts/channel_id/actor)",
    )
    parser.add_argument("--api", default="http://localhost:8000/api/v1", help="API base URL")
    parser.add_argument(
        "--out", default="bench_runs.json", help="Output JSON file path (default: bench_runs.json in CWD)"
    )
    args = parser.parse_args()

    events: list[Any] = []
    for line in Path(args.file).read_text().strip().split("\n"):
        line = line.strip()
        if line:
            events.append(json.loads(line))

    print(f"Ingesting {len(events)} events...")
    results: list[dict[str, object]] = []
    with httpx.Client(timeout=30.0) as client:
        for i, ev in enumerate(events):
            occurred_at = _parse_occurred_at(ev.get("ts"))
            body: dict[str, Any] = {
                "text": ev["raw_text"],
                "source_type": "slack",
                "source_id": ev["id"],
                "event_kind": "slack_message",
                "metadata": {
                    "bench": True,
                    "channel_id": ev.get("channel_id"),
                    "actor": ev.get("actor"),
                    "ts": ev.get("ts"),
                },
            }
            if occurred_at is not None:
                body["occurred_at"] = occurred_at
            try:
                r = client.post(
                    f"{args.api}/ingest/text",
                    headers={"X-Api-Key": args.key, "Content-Type": "application/json"},
                    json=body,
                )
                r.raise_for_status()
                data = r.json()["data"]
                results.append(
                    {
                        "src_id": ev["id"],
                        "event_id": data["event_id"],
                        "run_id": data["extraction_run_id"],
                        "status": data["status"],
                    }
                )
                print(
                    f"  [{i + 1:2d}/{len(events)}] {ev['id'][:8]}"
                    f" -> event={data['event_id'][:8]} run={data['extraction_run_id'][:8]}"
                )
            except Exception as e:
                print(f"  [{i + 1:2d}/{len(events)}] ERR: {e}")
                results.append({"src_id": ev["id"], "error": str(e)})

    out = Path(args.out)
    out.write_text(json.dumps(results, indent=2))
    ok = sum(1 for r in results if "run_id" in r)
    print(f"\nSuccess: {ok}/{len(events)}. Saved -> {out}")


if __name__ == "__main__":
    main()
