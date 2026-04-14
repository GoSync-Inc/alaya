"""Cortex-only evaluation: chunker + classifier on events (no extraction).

Usage:
    uv run python scripts/eval_cortex.py --file data/slack_export/slack_sample_40.jsonl
    uv run python scripts/eval_cortex.py --file ... --threshold 0.3 --no-verify

Outputs a JSON report to scripts/eval_results/ and prints a summary.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core"))


async def run_cortex(events, crystal_threshold: float = 0.1, verify: bool = True):
    from alayaos_core.config import Settings
    from alayaos_core.extraction.cortex.chunker import CortexChunker
    from alayaos_core.extraction.cortex.classifier import CortexClassifier
    from alayaos_core.extraction.sanitizer import sanitize
    from alayaos_core.llm.anthropic import AnthropicAdapter
    from alayaos_core.llm.interface import LLMUsage

    settings = Settings()
    api_key = settings.ANTHROPIC_API_KEY.get_secret_value()
    if not api_key:
        print("ERROR: ALAYA_ANTHROPIC_API_KEY not set in environment")
        sys.exit(1)

    model = settings.CORTEX_CLASSIFIER_MODEL
    print(f"Cortex eval — model: {model}, threshold: {crystal_threshold}, verify: {verify}")

    llm = AnthropicAdapter(api_key, model)
    chunker = CortexChunker()
    classifier = CortexClassifier(llm, crystal_threshold=crystal_threshold)

    results: list[dict] = []
    total_usage = LLMUsage(tokens_in=0, tokens_out=0, tokens_cached=0, cost_usd=0.0)

    for i, ev in enumerate(events):
        text = ev.get("raw_text") or ev.get("text") or ev.get("content") or ""
        if not text.strip():
            continue
        source_type = ev.get("source_type", "slack")
        source_id = str(ev.get("id", f"evt_{i}"))

        sanitized = sanitize(text)
        chunks = chunker.chunk(sanitized, source_type, source_id)

        event_result = {
            "id": source_id,
            "source_type": source_type,
            "text_len": len(text),
            "text_preview": text[:120].replace("\n", " "),
            "chunk_count": len(chunks),
            "chunks": [],
        }

        for chunk in chunks:
            try:
                if verify:
                    scores, changed, usage = await classifier.classify_and_verify(chunk)
                else:
                    scores, usage = await classifier.classify(chunk)
                    changed = False
            except Exception as e:
                event_result["chunks"].append({"index": chunk.index, "error": str(e)})
                continue

            is_crystal = classifier.is_crystal(scores)
            primary = classifier.primary_domain(scores)
            event_result["chunks"].append(
                {
                    "index": chunk.index,
                    "token_count": chunk.token_count,
                    "domain_scores": scores.model_dump(),
                    "primary": primary,
                    "is_crystal": is_crystal,
                    "verify_changed": changed,
                    "tokens_in": usage.tokens_in,
                    "tokens_out": usage.tokens_out,
                    "tokens_cached": usage.tokens_cached,
                    "cost_usd": usage.cost_usd,
                }
            )
            total_usage = LLMUsage(
                tokens_in=total_usage.tokens_in + usage.tokens_in,
                tokens_out=total_usage.tokens_out + usage.tokens_out,
                tokens_cached=total_usage.tokens_cached + usage.tokens_cached,
                cost_usd=total_usage.cost_usd + usage.cost_usd,
            )

        event_result["any_crystal"] = any(c.get("is_crystal") for c in event_result["chunks"])
        event_result["max_non_smalltalk"] = max(
            (
                v
                for c in event_result["chunks"]
                for d, v in c.get("domain_scores", {}).items()
                if d != "smalltalk"
            ),
            default=0.0,
        )
        event_result["smalltalk_score"] = max(
            (c.get("domain_scores", {}).get("smalltalk", 0.0) for c in event_result["chunks"]),
            default=0.0,
        )
        event_result["event_cost"] = sum(c.get("cost_usd", 0.0) for c in event_result["chunks"])

        primaries = [c.get("primary") for c in event_result["chunks"] if c.get("primary")]
        event_result["primary_display"] = primaries[0] if primaries else "n/a"

        print(
            f"  [{i + 1:2d}/{len(events)}] {source_id[:8]} "
            f"len={len(text):4d} chunks={len(chunks)} "
            f"crystal={event_result['any_crystal']!s:5} "
            f"primary={event_result['primary_display']:11} "
            f"max_non_st={event_result['max_non_smalltalk']:.2f} "
            f"st={event_result['smalltalk_score']:.2f} "
            f"${event_result['event_cost']:.4f}"
        )
        results.append(event_result)

    return results, total_usage


def summarize(results: list[dict], usage, threshold: float) -> dict:
    crystal = sum(1 for r in results if r["any_crystal"])
    total_chunks = sum(r["chunk_count"] for r in results)

    primary_dist = Counter()
    for r in results:
        for c in r["chunks"]:
            if "primary" in c:
                primary_dist[c["primary"]] += 1

    smalltalk_primary = sum(1 for r in results if r["primary_display"] == "smalltalk")
    verify_changed = sum(1 for r in results for c in r["chunks"] if c.get("verify_changed"))

    print(f"\n{'=' * 60}")
    print(f"  CORTEX SUMMARY ({len(results)} events)")
    print(f"{'=' * 60}")
    print(f"  Crystal (any chunk ≥ {threshold}): {crystal}/{len(results)} ({crystal / len(results) * 100:.1f}%)")
    print(f"  Primary=smalltalk:                 {smalltalk_primary}/{len(results)} ({smalltalk_primary / len(results) * 100:.1f}%)")
    print(f"  Total chunks:                       {total_chunks}")
    print(f"  Verify changed scores:              {verify_changed}")
    print(f"  Tokens: {usage.tokens_in} in / {usage.tokens_out} out / {usage.tokens_cached} cached")
    print(f"  Cost:   ${usage.cost_usd:.4f}")
    print(f"\n  Primary domain distribution (by chunk):")
    for d, n in primary_dist.most_common():
        print(f"    {d:12} {n}")
    print(f"{'=' * 60}\n")

    # Threshold sensitivity analysis — at what threshold would each event flip?
    for t in (0.1, 0.3, 0.5, 0.7):
        c = sum(1 for r in results if r["max_non_smalltalk"] >= t)
        print(f"  At threshold {t}: {c}/{len(results)} crystal ({c / len(results) * 100:.1f}%)")

    return {"crystal_count": crystal, "total": len(results), "primary_dist": dict(primary_dist)}


async def main():
    parser = argparse.ArgumentParser(description="Run Cortex classifier on events (no extraction)")
    parser.add_argument("--file", required=True, help="JSONL file of events")
    parser.add_argument("--threshold", type=float, default=0.1, help="is_crystal threshold")
    parser.add_argument("--no-verify", action="store_true", help="Skip double-pass verification")
    args = parser.parse_args()

    events = []
    for line in Path(args.file).read_text().strip().split("\n"):
        line = line.strip()
        if line:
            events.append(json.loads(line))

    results, usage = await run_cortex(events, args.threshold, verify=not args.no_verify)
    summary = summarize(results, usage, args.threshold)

    out_dir = Path(__file__).parent / "eval_results"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_cortex_{Path(args.file).stem}.json"
    out.write_text(
        json.dumps(
            {
                "source_file": str(args.file),
                "timestamp": datetime.now(UTC).isoformat(),
                "threshold": args.threshold,
                "verify": not args.no_verify,
                "usage": usage.model_dump(),
                "summary": summary,
                "events": results,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    asyncio.run(main())
