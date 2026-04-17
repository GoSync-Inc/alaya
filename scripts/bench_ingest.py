"""Ingest benchmark helper for Alaya.

POSTs a JSONL batch of events to /ingest/text, collects the returned
run_ids, and writes results to a JSON file for SQL follow-up queries.

Preconditions:
  - Alaya API server running (default: http://localhost:8000/api/v1)
  - TaskIQ worker running (processes the queued extraction jobs)
  - A valid API key created in the target workspace

Usage:
    uv run python scripts/bench_ingest.py --key ak_xxx
    uv run python scripts/bench_ingest.py --key ak_xxx --file data/slack_export/slack_sample_40.jsonl --out results.json
"""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ingest: POST events to /ingest/text")
    parser.add_argument("--key", required=True, help="API key (ak_xxx)")
    parser.add_argument("--file", default="data/slack_export/slack_sample_40.jsonl", help="JSONL events file")
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
            body = {
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
