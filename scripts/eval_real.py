"""Real data evaluation script for the extraction pipeline.

Usage:
    # Single text file:
    uv run python scripts/eval_real.py --file data/sample.txt

    # Directory of JSON files:
    uv run python scripts/eval_real.py --dir data/slack_export/

    # Inline text:
    uv run python scripts/eval_real.py --text "Alice mentioned Project Phoenix deadline is April 15"

    # From stdin:
    cat data/messages.txt | uv run python scripts/eval_real.py --stdin

Results are saved to scripts/eval_results/ (gitignored).
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core"))


async def run_extraction(text: str, source_type: str = "manual", source_id: str | None = None):
    """Run the full extraction pipeline on a single text input."""
    from alayaos_core.config import Settings
    from alayaos_core.extraction.extractor import Extractor
    from alayaos_core.extraction.preprocessor import Preprocessor
    from alayaos_core.extraction.sanitizer import sanitize
    from alayaos_core.extraction.schemas import ExtractionResult
    from alayaos_core.llm.interface import LLMUsage
    from alayaos_core.services.workspace import CORE_ENTITY_TYPES, CORE_PREDICATES

    settings = Settings()
    api_key = settings.ANTHROPIC_API_KEY.get_secret_value()

    if not api_key:
        print("ERROR: ALAYA_ANTHROPIC_API_KEY not set in .env")
        print("Add: ALAYA_ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    from alayaos_core.llm.anthropic import AnthropicAdapter

    llm = AnthropicAdapter(api_key, settings.ANTHROPIC_MODEL)
    preprocessor = Preprocessor()
    extractor = Extractor(llm, gleaning_enabled=False)  # Disable gleaning for speed

    # Build system prompt
    entity_types = [dict(et) for et in CORE_ENTITY_TYPES]
    predicates = [dict(p) for p in CORE_PREDICATES]
    system_prompt = extractor.build_system_prompt(entity_types, predicates)

    # Sanitize and chunk
    sanitized = sanitize(text)
    chunks = preprocessor.chunk(sanitized, source_type, source_id or str(uuid.uuid4()))

    print(f"\n--- Input: {len(text)} chars, {preprocessor.count_tokens(text)} tokens, {len(chunks)} chunk(s) ---")

    # Extract each chunk
    merged = ExtractionResult()
    total_usage = LLMUsage(tokens_in=0, tokens_out=0, tokens_cached=0, cost_usd=0.0)

    for i, chunk in enumerate(chunks):
        print(f"  Extracting chunk {i + 1}/{len(chunks)}...", end=" ", flush=True)
        result, usage = await extractor.extract_chunk(chunk, system_prompt)
        merged.entities.extend(result.entities)
        merged.relations.extend(result.relations)
        merged.claims.extend(result.claims)
        total_usage = LLMUsage(
            tokens_in=total_usage.tokens_in + usage.tokens_in,
            tokens_out=total_usage.tokens_out + usage.tokens_out,
            tokens_cached=total_usage.tokens_cached + usage.tokens_cached,
            cost_usd=total_usage.cost_usd + usage.cost_usd,
        )
        print(f"done ({len(result.entities)} entities, {len(result.claims)} claims, {len(result.relations)} relations)")

    return merged, total_usage


def print_results(result, usage, source_name: str = "input"):
    """Pretty-print extraction results."""
    print(f"\n{'=' * 60}")
    print(f"  EXTRACTION RESULTS: {source_name}")
    print(f"{'=' * 60}")

    print(f"\n  Tokens: {usage.tokens_in} in / {usage.tokens_out} out / {usage.tokens_cached} cached")
    print(f"  Cost: ${usage.cost_usd:.4f}")

    print(f"\n  ENTITIES ({len(result.entities)}):")
    for e in result.entities:
        aliases = f" (aliases: {', '.join(e.aliases)})" if e.aliases else ""
        ext_ids = f" [ext: {e.external_ids}]" if e.external_ids else ""
        print(f"    [{e.entity_type}] {e.name}{aliases}{ext_ids} (conf: {e.confidence:.2f})")

    print(f"\n  CLAIMS ({len(result.claims)}):")
    for c in result.claims:
        summary = f" — {c.source_summary}" if c.source_summary else ""
        print(f"    {c.entity} . {c.predicate} = {c.value} ({c.value_type}, conf: {c.confidence:.2f}){summary}")

    print(f"\n  RELATIONS ({len(result.relations)}):")
    for r in result.relations:
        print(f"    {r.source_entity} --[{r.relation_type}]--> {r.target_entity} (conf: {r.confidence:.2f})")

    print(f"\n{'=' * 60}\n")


def save_results(result, usage, source_name: str):
    """Save results to JSON file in eval_results/."""
    output_dir = Path(__file__).parent / "eval_results"
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    safe_name = source_name.replace("/", "_").replace(" ", "_")[:50]
    output_path = output_dir / f"{timestamp}_{safe_name}.json"

    data = {
        "source": source_name,
        "timestamp": datetime.now(UTC).isoformat(),
        "usage": usage.model_dump(),
        "entities": [e.model_dump() for e in result.entities],
        "claims": [c.model_dump() for c in result.claims],
        "relations": [r.model_dump() for r in result.relations],
        "summary": {
            "entity_count": len(result.entities),
            "claim_count": len(result.claims),
            "relation_count": len(result.relations),
            "entity_types": list({e.entity_type for e in result.entities}),
            "predicates_used": list({c.predicate for c in result.claims}),
        },
    }

    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"  Results saved to: {output_path}")
    return output_path


async def process_file(file_path: Path, source_type: str = "manual"):
    """Process a single file (JSON, JSONL, or plain text)."""
    if file_path.suffix == ".jsonl":
        return await process_jsonl(file_path, source_type)

    if file_path.suffix == ".json":
        data = json.loads(file_path.read_text())
        text = data.get("text", data.get("raw_text", data.get("content", data.get("body", ""))))
        source_type = data.get("source_type", source_type)
    else:
        text = file_path.read_text()

    if not text.strip():
        print(f"  Skipping {file_path.name} — empty")
        return None, None

    result, usage = await run_extraction(text, source_type, file_path.stem)
    print_results(result, usage, file_path.name)
    save_results(result, usage, file_path.name)
    return result, usage


async def process_jsonl(file_path: Path, source_type: str = "manual"):
    """Process JSONL file — one JSON object per line."""
    lines = file_path.read_text().strip().split("\n")
    print(f"\nProcessing {len(lines)} events from {file_path.name}...")

    all_entities = 0
    all_claims = 0
    all_relations = 0
    total_cost = 0.0
    all_results = []

    for i, line in enumerate(lines):
        data = json.loads(line)
        text = data.get("raw_text", data.get("text", data.get("content", "")))
        src_type = data.get("source_type", source_type)
        event_id = data.get("id", f"event_{i}")

        if not text or not text.strip() or len(text.strip()) < 20:
            print(f"  [{i + 1}/{len(lines)}] Skipping {event_id[:8]}... — too short")
            continue

        try:
            result, usage = await run_extraction(text.replace("\x00", ""), src_type, str(event_id)[:8])
            print_results(result, usage, f"event_{i + 1}_{event_id[:8]}")
            save_results(result, usage, f"event_{i + 1}_{event_id[:8]}")

            all_entities += len(result.entities)
            all_claims += len(result.claims)
            all_relations += len(result.relations)
            total_cost += usage.cost_usd
            all_results.append({"event_id": event_id, "result": result, "usage": usage})
        except Exception as e:
            print(f"  [{i + 1}/{len(lines)}] ERROR: {e}")

    print(f"\n{'=' * 60}")
    print(f"  BATCH SUMMARY: {file_path.name}")
    print(f"  Events processed: {len(all_results)}/{len(lines)}")
    print(f"  Total entities: {all_entities}")
    print(f"  Total claims: {all_claims}")
    print(f"  Total relations: {all_relations}")
    print(f"  Total cost: ${total_cost:.4f}")
    if all_results:
        print(f"  Avg entities/event: {all_entities / len(all_results):.1f}")
        print(f"  Avg claims/event: {all_claims / len(all_results):.1f}")
    print(f"{'=' * 60}")

    return None, None  # batch mode


async def main():
    parser = argparse.ArgumentParser(description="Run extraction pipeline on real data")
    parser.add_argument("--file", type=str, help="Path to a single text/JSON file")
    parser.add_argument("--dir", type=str, help="Path to directory of text/JSON files")
    parser.add_argument("--text", type=str, help="Inline text to extract from")
    parser.add_argument("--stdin", action="store_true", help="Read text from stdin")
    parser.add_argument("--source-type", type=str, default="manual", help="Source type (slack, github, manual)")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process from --dir")
    args = parser.parse_args()

    if args.text:
        result, usage = await run_extraction(args.text, args.source_type)
        print_results(result, usage, "inline")
        save_results(result, usage, "inline")

    elif args.stdin:
        text = sys.stdin.read()
        result, usage = await run_extraction(text, args.source_type)
        print_results(result, usage, "stdin")
        save_results(result, usage, "stdin")

    elif args.file:
        await process_file(Path(args.file), args.source_type)

    elif args.dir:
        dir_path = Path(args.dir)
        files = sorted(dir_path.glob("*"))
        files = [f for f in files if f.is_file() and f.suffix in (".txt", ".json", ".md")]
        if args.limit > 0:
            files = files[: args.limit]

        print(f"Processing {len(files)} files from {dir_path}...")

        all_entities = 0
        all_claims = 0
        all_relations = 0
        total_cost = 0.0

        for f in files:
            try:
                result, usage = await process_file(f, args.source_type)
                if result:
                    all_entities += len(result.entities)
                    all_claims += len(result.claims)
                    all_relations += len(result.relations)
                    total_cost += usage.cost_usd
            except Exception as e:
                print(f"  ERROR processing {f.name}: {e}")

        print(f"\n{'=' * 60}")
        print("  BATCH SUMMARY")
        print(f"  Files: {len(files)}")
        print(f"  Entities: {all_entities}")
        print(f"  Claims: {all_claims}")
        print(f"  Relations: {all_relations}")
        print(f"  Total cost: ${total_cost:.4f}")
        print(f"{'=' * 60}")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
