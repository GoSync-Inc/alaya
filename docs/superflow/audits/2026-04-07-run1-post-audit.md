# Run 1 Post-Audit: Findings & Action Items

**Date:** 2026-04-07
**Reviewers:** Claude (deep-code-reviewer, best-practices-researcher), Codex (product audit)

## Run 1.1 (Patch — before Run 2)

### Code Fixes
- [ ] SET LOCAL: validate UUID before f-string interpolation (CRITICAL — SQL injection vector)
- [ ] Defense-in-depth: add `workspace_id` filter to ALL repository queries (HIGH)
- [ ] Event upsert: replace select-then-insert with `INSERT ON CONFLICT DO UPDATE` (HIGH)
- [ ] Workspace update: add allowed-fields whitelist like EntityRepository (HIGH)
- [ ] PATCH endpoints: `exclude_unset=True` instead of `exclude_none=True` (MEDIUM)
- [ ] Exception handler: add `logger.exception()` before returning 500 (MEDIUM)
- [ ] Validation errors: strip `input` from Pydantic error details in hint (MEDIUM)
- [ ] Lazy relationships: set `lazy="raise"` on entity_type relationship (MEDIUM)
- [ ] Engine: add pool_size/max_overflow/pool_recycle config (MEDIUM)
- [ ] Seed script: wrap in explicit `async with session.begin()` (CRITICAL)

### DX / DevOps
- [ ] Fix `uv run pytest` — needs `uv sync --all-packages --dev` in docs
- [ ] Add `Makefile` or `justfile` with common commands
- [ ] Add structlog for JSON logging
- [ ] CI: Docker build + push to GHCR
- [ ] CI: Trivy image scan (pin action by SHA)
- [ ] CI: Squawk migration linter
- [ ] CI: `pip-audit` / `uv audit`
- [ ] Deploy workflow: GHCR + SSH + blue-green Caddy script

## Run 2 (Extraction Pipeline) — Additional Scope

### Data Model Prep
- [ ] `l0_events`: add `raw_text`, `occurred_at`, `event_kind`, `actor_external_id`, `mentioned_external_ids`, `access_level`, `access_context`, `is_extracted`/`extraction_status`
- [ ] `l1_entities`: add `aliases TEXT[]`, `version INTEGER`
- [ ] `l2_claims`: activate from stub — add `value_type`, `value_ref`, `level`, `premise_claim_ids`, `source_summary`, `observed_at`, `estimated_start`, `supersedes`, `status`
- [ ] `entity_external_ids`: add unique constraint on `(workspace_id, source_type, external_id)` to prevent same external ID on multiple entities
- [ ] Core entity types: add `task` and `organization` to seeds
- [ ] Claims/Relations repositories and services (internal, no public API yet)

### Infrastructure
- [ ] TaskIQ async workers for extraction pipeline
- [ ] Prometheus metrics (`prometheus-fastapi-instrumentator`)
- [ ] Sentry integration
- [ ] SOPS for encrypted secrets
- [ ] Backward-compatible migration policy in CLAUDE.md

## Run 3+ (Search, CLI, Connectors) — Backlog

### Retrieval Engine (Run 3) — unified architecture, ideas from MemPalace + Holographic Memory + own R&D

**Tri-signal hybrid scoring** — единая формула ранжирования на PostgreSQL:
- [ ] Signal 1 — Semantic: pgvector cosine similarity (embeddings)
- [ ] Signal 2 — Lexical: `pg_trgm` + FTS for BM25-like keyword matching
- [ ] Signal 3 — Structural: entity Jaccard overlap (shared entities between query and claim)
- [ ] Fusion: `score = (w1·semantic + w2·lexical + w3·structural) * trust * temporal_decay`
- [ ] Reranker abstraction (`RerankerInterface` in core) — optional LLM rerank for top-N

**Temporal intelligence:**
- [ ] Bi-temporal model in claims (valid_from/valid_to + recorded_at)
- [ ] Temporal boost: parse relative dates ("a week ago", "last month"), boost claims by temporal proximity to query date
- [ ] Dynamic forgetting: `decay = 0.5^(age_days / half_life)` — configurable per workspace

**Contradiction detection** — periodic TaskIQ job:
- [ ] Algorithm: claims sharing entities (high Jaccard) + divergent content (low cosine) → conflict candidates
- [ ] Store in `claim_conflicts` table with `conflict_score`, `detected_at`
- [ ] Surface via API: `GET /claims/{id}/conflicts`
- [ ] Inspired by: Holographic Memory contradict() + MemPalace knowledge graph invalidation

**Trust scoring with asymmetric feedback:**
- [ ] `helpful` → trust += 0.05, `unhelpful` → trust -= 0.10 (negative feedback weighs 2x)
- [ ] Trust score [0, 1] multiplied into retrieval ranking
- [ ] API: `POST /claims/{id}/feedback` with `{verdict: "helpful"|"unhelpful"}`

**Layered agent context** (progressive disclosure, NOT the L0-L3 data model):
- [ ] Wake-up (~100 tokens): workspace name, key entities count, recent activity summary
- [ ] Summary (~500-800 tokens): top L1 Entities + their L2 Claims by trust × recency — entities give "who/what", claims give "facts about them"
- [ ] Scoped query: agent calls search filtered by entity/predicate — returns L2 Claims + L3 Relations
- [ ] Deep search: full tri-signal hybrid across all layers including raw L0 Events

**Benchmark:**
- [ ] LongMemEval harness: adapter to ingest chat sessions → L0 events → extraction → retrieval → QA eval (target: >85% end-to-end accuracy, oracle baseline = 82.4%)

### Zero-LLM Extraction Fallback (Run 3, inspired by MemPalace)
- [ ] Add regex/keyword heuristic extractor as fallback mode alongside LLM extraction
- [ ] Pattern library: decisions ("we went with X because Y"), preferences ("I prefer X"), milestones, problems
- [ ] Entity detection: two-pass regex (capitalized proper nouns + scoring by signals)
- [ ] Config: `EXTRACTION_MODE=llm|heuristic|hybrid` — hybrid runs heuristic first, LLM for ambiguous cases
- [ ] Rationale: MemPalace proved 96.6% retrieval recall with zero LLM cost; useful as cheap baseline and offline fallback

### Product
- [ ] MCP Server — consider moving from Run 6 to Run 3-4
- [ ] MCP Memory Protocol: embed AI instructions in MCP responses ("verify before responding", "when facts change → invalidate + add") — proven to improve accuracy (MemPalace pattern)
- [ ] MCP wake-up context: AAAK-like compressed summary (~170 tokens) sent on initial connection — entity codes, key claims, recent changes. Avoids loading full context on every agent startup
- [ ] Personalized agent briefings: `GET /context/briefing?person={entity_id}&format=markdown|json`
  - [ ] Resolves person → role (L2 Claims, predicate=role) → tailored projection of the knowledge graph
  - [ ] Developer: my tasks, blockers, upcoming deadlines, relevant PRs
  - [ ] Lead/Manager: team status, risks, overdue items, resource allocation
  - [ ] Executive: project portfolio, budget, headcount, red/yellow/green status
  - [ ] ACL-filtered: only shows data the person has access to (access_level on events)
  - [ ] Dual output: markdown (for agent startup / CLAUDE.md-style injection) + JSON (for runtime API calls)
  - [ ] Refresh: periodic regeneration (hourly?) or on-demand via API
- [ ] Python SDK (`pip install alayaos`) — by Run 4-5
- [ ] CORS middleware — before web UI (Run 7)
- [ ] API versioning / ETag for optimistic concurrency

### Stubs Alignment
- [ ] `l3_tree_nodes`: add `parent_id`, `title`, `content_markdown`, `staleness_score`, `last_rebuilt`
- [ ] `vector_chunks`: remove hardcoded `vector(1536)`, add ACL context
- [ ] ACL tables: add `person_entity_id`, `email`, `source`, `source_id`
- [ ] `api_keys`: add `person_id`, `last_used_at`
- [ ] `claim_sources`/`relation_sources`: composite PK instead of surrogate UUID

## Competitor Insights

| Insight | Source | Action |
|---------|--------|--------|
| Don't copy multi-DB architecture | mem0 (3 DBs = ops hell) | Stay with PostgreSQL-only |
| Temporal invalidation > deletion | Graphiti | Implement in claims (Run 2) |
| Async memory writes critical | Industry consensus | TaskIQ workers in Run 2 |
| Procedural memory gap | mem0 v1.0 | Consider for Run 3+ |
| Benchmarks for positioning | LongMemEval, LoCoMo, ConvoMem | Run after extraction works |
| Verbatim + embeddings beats LLM extraction for retrieval | MemPalace (96.6% Recall@5 no LLM) | Zero-LLM fallback mode in Run 3 |
| Hierarchical navigation +34% retrieval | MemPalace palace structure | Layered retrieval stack in Run 3 |
| Compressed wake-up context ~30x | MemPalace AAAK dialect | MCP wake-up summary in Run 3-4 |
| AI Memory Protocol improves accuracy | MemPalace MCP instructions | Embed in MCP server (Run 3-4) |
| Hybrid scoring (embed + keyword) → 100% | MemPalace hybrid_v4 + rerank | Tri-signal scoring in Run 3 |
| LongMemEval oracle baseline = 82.4% | ICLR 2025 paper | Target >85% e2e for Alaya (Run 3) |
| Tri-signal scoring (semantic + lexical + structural) | Hermes Holographic Memory | Unified fusion formula in Run 3 |
| Algebraic contradiction detection (entity overlap + content divergence) | Hermes Holographic Memory | `claim_conflicts` table + periodic job in Run 3 |
| Asymmetric trust feedback (unhelpful = 2x penalty) | Hermes Holographic Memory | Trust scoring on claims in Run 3 |
| Compositional multi-entity queries via HRR prefilter | Hermes Holographic Memory | Evaluate as optional prefilter layer in Run 3 |

## DevOps Recommendations

| Priority | What | Effort | When |
|----------|------|--------|------|
| Must | structlog + JSON logging | Low | Run 1.1 |
| Must | GHCR + Trivy + Squawk in CI | Low | Run 1.1 |
| Must | Deploy workflow (GHCR + SSH) | Medium | Run 1.1 |
| Should | Blue-green via Caddy | Medium | Run 1.1 |
| Should | Prometheus metrics | Low | Run 2 |
| Should | Sentry | Low | Run 2 |
| Should | SOPS secrets | Medium | Run 2 |
| Could | Kamal (if multi-server) | High | Run 3+ |
| Could | OpenTelemetry tracing | High | Run 3+ |

<!-- updated-by-superflow:2026-04-07 -->
