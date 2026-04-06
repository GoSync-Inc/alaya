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

### Search (Run 3)
- [ ] Hybrid search: pgvector + `pg_trgm` for BM25-like keyword search
- [ ] Reranker abstraction (`RerankerInterface` in core)
- [ ] Temporal facts: bi-temporal model in claims (valid_from/valid_to + recorded_at)
- [ ] Dynamic forgetting / decay mechanism

### Product
- [ ] MCP Server — consider moving from Run 6 to Run 3-4
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
