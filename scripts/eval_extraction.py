"""Extraction pipeline evaluation script — Run 2 vs Run 3 comparison.

Dry-run eval using FakeLLMAdapter (no real LLM calls).
Compares old extraction pipeline (Run 2) with new Cortex+Crystallizer
pipeline (Run 3) for 5 sample events.

Usage:
    uv run python scripts/eval_extraction.py
"""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core"))

# ── Sample events ─────────────────────────────────────────────────────────────

SAMPLE_EVENTS = [
    {
        "id": "ev-001",
        "source_type": "slack",
        "source_id": "C1234/general",
        "text": (
            "Alice: Hey team, just confirmed with the client — Project Phoenix deadline is April 15.\n"
            "Bob: Got it, I'll update the roadmap.\n"
            "Alice: Also, Bob is now the owner of the backend module.\n"
            "Carol: Should we add this to the project tracker?\n"
            "Bob: Yes, please. Set status to 'in progress'."
        ),
    },
    {
        "id": "ev-002",
        "source_type": "meeting_transcript",
        "source_id": "meet-2024-03-15",
        "text": (
            "Manager: Let's start with the Q2 OKR review. Our goal is 40% cost reduction on LLM calls.\n"
            "Engineer: We're implementing Haiku for classification — early tests show 60% cost drop.\n"
            "Manager: Great. Any blockers?\n"
            "Engineer: Redis latency spike last Friday, but resolved now.\n"
            "Manager: Mark it as resolved in the risk register."
        ),
    },
    {
        "id": "ev-003",
        "source_type": "document",
        "source_id": "doc-onboarding-v3",
        "text": (
            "Onboarding Guide — Engineering Team\n\n"
            "1. Set up your development environment following the README.\n"
            "2. Request access to the staging database from DevOps (currently Dan).\n"
            "3. Your first task will be assigned by your team lead (currently Sarah).\n\n"
            "Security policy: All API keys must use the ak_ prefix and SHA-256 hashing."
        ),
    },
    {
        "id": "ev-004",
        "source_type": "slack",
        "source_id": "C9999/random",
        "text": ("lol that meeting could've been an email\n😂😂\nagreed\n+1\nsame time next week?"),
    },
    {
        "id": "ev-005",
        "source_type": "meeting_transcript",
        "source_id": "meet-2024-04-01",
        "text": (
            "CEO: Strategic update — we are pivoting to focus on enterprise customers.\n"
            "Head of Sales: Target ARR for Q3 is $2M. Current pipeline is at $800K.\n"
            "CTO: The data platform migration to PostgreSQL is complete. RLS policies are live.\n"
            "CEO: Risk: if we miss Q3, we revisit the roadmap. Decision: all hands on enterprise deals.\n"
            "Head of Sales: I'll own the enterprise outreach. Deadline: end of April."
        ),
    },
]


# ── Run 2: FakeLLMAdapter extraction (old pipeline) ────────────────────────────


@dataclass
class Run2Result:
    event_id: str
    entities: int
    relations: int
    claims: int
    tokens_in: int
    tokens_out: int
    cost_usd: float


async def run2_extract(event: dict) -> Run2Result:
    """Run extraction using the old Run 2 pipeline (FakeLLMAdapter)."""
    from alayaos_core.extraction.extractor import Extractor
    from alayaos_core.extraction.preprocessor import Preprocessor
    from alayaos_core.llm.fake import FakeLLMAdapter
    from alayaos_core.services.workspace import CORE_ENTITY_TYPES, CORE_PREDICATES

    llm = FakeLLMAdapter()
    preprocessor = Preprocessor()
    extractor = Extractor(llm, gleaning_enabled=False)

    entity_types = [dict(et) for et in CORE_ENTITY_TYPES]
    predicates = [dict(p) for p in CORE_PREDICATES]
    system_prompt = extractor.build_system_prompt(entity_types, predicates)

    text = event["text"]
    source_type = event["source_type"]
    source_id = event["source_id"]
    chunks = preprocessor.chunk(text, source_type, source_id)

    all_entities = []
    all_relations = []
    all_claims = []
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0

    for chunk in chunks:
        result, usage = await extractor.extract_chunk(chunk, system_prompt)
        all_entities.extend(result.entities)
        all_relations.extend(result.relations)
        all_claims.extend(result.claims)
        total_tokens_in += usage.tokens_in
        total_tokens_out += usage.tokens_out
        total_cost += usage.cost_usd

    return Run2Result(
        event_id=event["id"],
        entities=len(all_entities),
        relations=len(all_relations),
        claims=len(all_claims),
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
        cost_usd=total_cost,
    )


# ── Run 3: CortexChunker + CortexClassifier (new pipeline) ────────────────────


@dataclass
class Run3Result:
    event_id: str
    chunks_total: int
    chunks_crystal: int
    chunks_skipped: int
    primary_domains: list[str]
    tokens_in: int
    tokens_out: int
    cost_usd: float


async def run3_classify(event: dict) -> Run3Result:
    """Run Cortex chunking + classification using FakeLLMAdapter."""
    from alayaos_core.extraction.cortex.chunker import CortexChunker
    from alayaos_core.extraction.cortex.classifier import CortexClassifier
    from alayaos_core.llm.fake import FakeLLMAdapter

    chunker = CortexChunker(max_chunk_tokens=3000)
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm=llm, crystal_threshold=0.1)

    text = event["text"]
    source_type = event["source_type"]
    source_id = event["source_id"]

    raw_chunks = chunker.chunk(text, source_type, source_id)

    chunks_crystal = 0
    chunks_skipped = 0
    primary_domains: list[str] = []
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0

    for rc in raw_chunks:
        scores, _changed, usage = await classifier.classify_and_verify(rc)
        is_crystal = classifier.is_crystal(scores)
        primary = classifier.primary_domain(scores)

        if is_crystal:
            chunks_crystal += 1
        else:
            chunks_skipped += 1

        primary_domains.append(primary)
        total_tokens_in += usage.tokens_in
        total_tokens_out += usage.tokens_out
        total_cost += usage.cost_usd

    return Run3Result(
        event_id=event["id"],
        chunks_total=len(raw_chunks),
        chunks_crystal=chunks_crystal,
        chunks_skipped=chunks_skipped,
        primary_domains=primary_domains,
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
        cost_usd=total_cost,
    )


# ── Comparison table ───────────────────────────────────────────────────────────


def _print_separator(width: int = 120) -> None:
    print("-" * width)


def _print_header() -> None:
    print()
    print("=" * 120)
    print(" Alaya Extraction Pipeline — Run 2 vs Run 3 Comparison (dry-run, FakeLLMAdapter)")
    print("=" * 120)


def _print_run2_table(results: list[Run2Result]) -> None:
    print()
    print("[ Run 2: Old Pipeline — Single-pass FakeLLM extraction ]")
    _print_separator()
    print(
        f"{'Event':<10} {'Entities':>8} {'Relations':>10} {'Claims':>7} {'Tokens In':>10} {'Tokens Out':>11} {'Cost USD':>10}"
    )
    _print_separator()
    for r in results:
        print(
            f"{r.event_id:<10} {r.entities:>8} {r.relations:>10} {r.claims:>7} {r.tokens_in:>10} {r.tokens_out:>11} {r.cost_usd:>10.6f}"
        )
    _print_separator()
    total_entities = sum(r.entities for r in results)
    total_cost = sum(r.cost_usd for r in results)
    print(f"{'TOTAL':<10} {total_entities:>8}                              {total_cost:>10.6f}")


def _print_run3_table(results: list[Run3Result]) -> None:
    print()
    print("[ Run 3: New Pipeline — CortexChunker + CortexClassifier ]")
    _print_separator()
    print(
        f"{'Event':<10} {'Chunks':>7} {'Crystal':>8} {'Skipped':>8} {'Domains':<30} {'Tokens In':>10} {'Cost USD':>10}"
    )
    _print_separator()
    for r in results:
        domains_str = ", ".join(r.primary_domains[:3]) + ("..." if len(r.primary_domains) > 3 else "")
        print(
            f"{r.event_id:<10} {r.chunks_total:>7} {r.chunks_crystal:>8} {r.chunks_skipped:>8} {domains_str:<30} {r.tokens_in:>10} {r.cost_usd:>10.6f}"
        )
    _print_separator()
    total_chunks = sum(r.chunks_total for r in results)
    total_crystal = sum(r.chunks_crystal for r in results)
    total_cost = sum(r.cost_usd for r in results)
    print(
        f"{'TOTAL':<10} {total_chunks:>7} {total_crystal:>8}                                              {total_cost:>10.6f}"
    )


def _print_comparison(run2: list[Run2Result], run3: list[Run3Result]) -> None:
    print()
    print("[ Comparison Summary ]")
    _print_separator()
    print(f"{'Metric':<40} {'Run 2':>15} {'Run 3':>15} {'Delta':>15}")
    _print_separator()

    r2_total_tokens = sum(r.tokens_in + r.tokens_out for r in run2)
    r3_total_tokens = sum(r.tokens_in + r.tokens_out for r in run3)
    r2_cost = sum(r.cost_usd for r in run2)
    r3_cost = sum(r.cost_usd for r in run3)
    r3_crystal = sum(r.chunks_crystal for r in run3)
    r3_total = sum(r.chunks_total for r in run3)
    r3_skipped = sum(r.chunks_skipped for r in run3)

    crystal_pct = (r3_crystal / r3_total * 100) if r3_total > 0 else 0
    token_delta = r3_total_tokens - r2_total_tokens
    cost_delta = r3_cost - r2_cost

    print(f"{'Total tokens (in+out)':<40} {r2_total_tokens:>15} {r3_total_tokens:>15} {token_delta:>+15}")
    print(f"{'Total cost USD':<40} {r2_cost:>15.6f} {r3_cost:>15.6f} {cost_delta:>+15.6f}")
    print(f"{'Crystal chunks (Run 3)':<40} {'N/A':>15} {r3_crystal:>15} {'':>15}")
    print(f"{'Skipped chunks (Run 3)':<40} {'N/A':>15} {r3_skipped:>15} {'':>15}")
    print(f"{'Crystal selection rate':<40} {'N/A':>15} {crystal_pct:>14.1f}% {'':>15}")
    _print_separator()
    print()
    print("Notes:")
    print("  - FakeLLMAdapter returns deterministic minimal responses (no real LLM calls)")
    print("  - Cost is 0.0 for FakeLLMAdapter; in production Haiku costs ~$0.25/MTok")
    print("  - Crystal threshold: 0.1 (any domain score ≥ 0.1 → crystal)")
    print("  - Run 3 skips smalltalk/low-signal chunks before expensive Sonnet extraction")
    print()


async def main() -> None:
    _print_header()

    print()
    print("Running Run 2 extraction for 5 sample events...")
    run2_results: list[Run2Result] = []
    for event in SAMPLE_EVENTS:
        try:
            result = await run2_extract(event)
            run2_results.append(result)
            print(f"  [{event['id']}] entities={result.entities} claims={result.claims}")
        except Exception as exc:
            print(f"  [{event['id']}] ERROR: {exc}")
            # Use zero result on error
            run2_results.append(
                Run2Result(
                    event_id=event["id"],
                    entities=0,
                    relations=0,
                    claims=0,
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                )
            )

    print()
    print("Running Run 3 Cortex classification for 5 sample events...")
    run3_results: list[Run3Result] = []
    for event in SAMPLE_EVENTS:
        try:
            result = await run3_classify(event)
            run3_results.append(result)
            print(
                f"  [{event['id']}] chunks={result.chunks_total} crystal={result.chunks_crystal} domains={result.primary_domains[:2]}"
            )
        except Exception as exc:
            print(f"  [{event['id']}] ERROR: {exc}")
            run3_results.append(
                Run3Result(
                    event_id=event["id"],
                    chunks_total=0,
                    chunks_crystal=0,
                    chunks_skipped=0,
                    primary_domains=[],
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                )
            )

    _print_run2_table(run2_results)
    _print_run3_table(run3_results)
    _print_comparison(run2_results, run3_results)


if __name__ == "__main__":
    asyncio.run(main())
