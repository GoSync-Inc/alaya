# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **BREAKING** `/admin/backfill-embeddings` is now workspace-bound for non-bootstrap admin keys.
  Non-bootstrap keys must supply `workspace_id` (their own workspace); omitting it returns 422
  `workspace_required_for_admin_scope`. Supplying a different workspace returns 403
  `auth.cross_workspace_denied`. Bootstrap keys retain full cross-workspace access.
  Cross-workspace attempts are logged as `admin_cross_workspace_attempt` audit events.

### Added

- **Migration 007** — multi-tenant hardening for three join tables that previously lacked
  workspace-scoping (`claim_sources`, `relation_sources`, `access_group_members`):
  - `workspace_id UUID NOT NULL` column backfilled from parent table before adding the constraint.
  - Composite FK constraints: `(workspace_id, claim_id) → l2_claims`, `(workspace_id, event_id) → l0_events`,
    `(workspace_id, relation_id) → l1_relations`, `(workspace_id, group_id) → access_groups`,
    `(workspace_id, member_id) → workspace_members`.
  - `CONCURRENTLY` indexes on `workspace_id` for each join table (safe for live installs with data).
  - `ENABLE ROW LEVEL SECURITY + FORCE ROW LEVEL SECURITY + policy WITH CHECK` on all three tables.
  - Fully reversible `downgrade()`: drops RLS, composite FKs, workspace_id, restores original single-column FKs.
- **Security hotfix (PR #98)** — rate-limit on `POST /ingest/text` (default 30 req/min/key, fail-closed on
  Redis outage); `DATABASE_URL` / `REDIS_URL` wrapped in `SecretStr` at every call-site;
  `hmac.compare_digest` for API-key hash comparison; production startup guard rejects default /
  blank `SECRET_KEY`; `_sanitize_context` in `/ask` normalizes via NFKC + strips Unicode `Cf`
  category (zero-width / bidi-override bypasses); two-pass sanitization catches cross-snippet
  injection; idempotent-retry gate prevents duplicate LLM work on pending-run retries.

## [0.7.0] - Run 5.4 Knowledge Graph Consolidation

### Added

- **Panoramic triage pass** — normalizes entities across the full workspace before dedup; reclassifies, rewrites, and enforces hierarchy constraints.
- **Dedup v2** — composite signal (name similarity + embedding cosine + co-event score) with drop gate, merge-with-rewrite, N=9 batch size per LLM call.
- **Multi-pass integrator orchestrator** — convergence loop with cost tracking and action persistence; `job_check_integrator` periodic worker.
- **`integrator_actions` table** — audit log for every integrator merge/split/rewrite action with rollback API (`POST /integrator-actions/{id}/rollback`).
- Migration 006 (`consolidator_schema`) — `integrator_actions` table.

### Changed

- Crystallizer prompt v2: hierarchy guidance, date normalization examples, bilingual (EN/RU) support.
- Vector shortlist dedup: configurable `INTEGRATOR_DEDUP_SHORTLIST_K`, `INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD`, `INTEGRATOR_DEDUP_BATCH_SIZE`.
- `CONSOLIDATOR_PANORAMIC_MAX_ENTITIES` cap (default `500`) added for panoramic pass.

### Fixed

- Cluster rollback now correctly removes associated relations.
- Cycle hash made stable; enrichment reload on re-run corrected.
- `noise_removed` counter and v1 merge audit records corrected.
- S6 review: flush-not-commit, entity refresh, cycle detection, rewrite params.

## [0.6.0] - Run 5.3 Extraction Reliability

### Added

- **Smalltalk-aware `is_crystal`** — chunks containing only greetings/pleasantries skip LLM extraction.
- **List coercion in Anthropic adapter** — top-level `list[...]` / `list[...] | None` fields coerced from JSON strings before Pydantic validation (`_coerce_list_strings`).
- **Usage aggregation** — `ExtractionRunRepository.recalc_usage` SUMs `tokens_in`/`cost_usd` from `pipeline_traces` at every terminal transition; skipped for zero-trace paths.
- **Vector shortlist dedup** — FastEmbed cosine top-K per entity type gates LLM verification pass.

### Fixed

- Reasoning limit applied to crystallizer to prevent runaway token usage.
- Failure envelopes: `job_cortex`, `job_crystallize`, `job_write` call `mark_failed` on exception.
- Usage recalculation for zero-crystal and legacy non-Cortex paths.

## [0.5.0] - Run 5.2 Security Hardening

### Added

- **Rate limiter fail-closed** — `POST /search` and `POST /ask` return 503 when Redis backend is unavailable.
- **`ASK_RATE_LIMIT_PER_MINUTE` / `ASK_RATE_LIMIT_PER_HOUR`** config knobs.
- **API docs gating** — `ALAYA_API_DOCS_ENABLED` defaults off in production.
- **Trusted hosts middleware** — `ALAYA_TRUSTED_HOSTS` enforces `Host` header validation; request IDs preserved through validation failures.
- **Health and setup secret hardening** — reduced secret leakage surface in health endpoints and CLI setup.

### Fixed

- SBP-001–006 security findings from Run 5.2 audit.
- Worker DB engine re-use per process (prevents connection exhaustion under load).

### BREAKING

- `POST /ask` and `POST /search` return 503 (not 500) when rate limiter Redis backend is unavailable.

## [0.4.0] - Run 5.1 Review Follow-up

### Fixed

- DB workspace write lock: tightened coverage to prevent concurrent integrator runs from corrupting state.
- Integrator run reuse: API-created integrator runs now correctly reused by the worker (stale errors cleared on resume).
- Worker DB engine pre-warmed to reduce first-request latency.

## [0.3.0] - Run 3 Intelligence Pipeline

### Added

- **Integrator** (`extraction/integrator/`) — multi-pass knowledge graph consolidation:
  - Entity deduplication via vector shortlist + LLM verification.
  - Enricher — fills missing entity fields from existing claims.
  - `DateNormalizerPass` — resolves relative date expressions via `dateparser`.
  - `IntegratorRun` tracking with status + action audit.
- **Hybrid search** (`POST /search`) — 3-channel Reciprocal Rank Fusion: pgvector HNSW cosine + FTS `websearch_to_tsquery` + `pg_trgm` entity name similarity. Rate-limited (fail-closed on Redis unavailability).
- **Q&A** (`POST /ask`) — search → token budget → XML prompt → LLM → citation validation; prompt injection protection via context sanitization.
- **Knowledge tree** (`GET /tree`, `GET /tree/{path}`, `POST /tree/export`) — materialized briefing layer, dirty-flag rebuild, LLM synthesis with 6 s timeout + raw-claims fallback.
- **Embedding pipeline** — FastEmbed `multilingual-e5-large` (1024d halfvec); batch backfill via `job_enrich`.
- **Go CLI** (`packages/cli-go/`) — Cobra single-binary: `search`, `ask`, `entity`, `claim`, `tree`, `ingest`, `key`, `workspace`, `setup agent`. OS keyring auth. Dual-mode output (human/JSON). `alaya setup agent --profile claude-code` generates MCP config.
- Migrations 005a/005b — search columns + HNSW indexes.
- `pipeline_traces` table — per-step execution details.
- `integrator_runs` table — integration run tracking.

### Changed

- `POST /ingest` endpoint path changed to `POST /ingest/text`.
- Worker tasks expanded: `job_enrich`, `job_integrate`, `job_check_integrator` added alongside Run 2 tasks.

## [0.2.0] - Run 2 Extraction Pipeline

### Added

- **Cortex** (`extraction/cortex/`) — chunks raw event text into `L0Chunk` records; classifies chunk type (narrative, list, table, code, etc.) to guide downstream extraction. Migration 003 adds `l0_chunks` table.
- **Crystallizer** (`extraction/crystallizer/`) — LLM extraction per chunk with structured prompt boundary (`<instructions>`, `<ontology>`, `<data>` XML tags); gleaning loop; confidence scoring. Produces `ExtractionResult` (entities + claims + relations).
- **Writer** (`extraction/writer.py`) — atomic persist with dirty-set trigger and workspace write lock.
- **Resolver** (`extraction/resolver.py`) — 3-tier entity resolution: exact match → fuzzy (rapidfuzz) → LLM disambiguation with transliteration support.
- **Sanitizer** (`extraction/sanitizer.py`) — NFKC normalization, zero-width stripping, HTML comment removal, injection pattern detection.
- **Anthropic adapter** — provider-native tool-call / JSON structured output with prompt caching; per-stage model config (`CORTEX_CLASSIFIER_MODEL`, `CRYSTALLIZER_MODEL`, `INTEGRATOR_MODEL`).
- **`FakeLLMAdapter`** — deterministic test responses with domain-specific overrides.
- **TaskIQ worker** — broker + `job_extract`, `job_write`, `job_cortex`, `job_crystallize` tasks. All params are string IDs — raw text never passed via job queue.
- Migration 004 — `extraction_run` + `pipeline_traces` tables and intelligence pipeline schema.
- `POST /ingest` endpoint — triggers extraction pipeline, returns `extraction_run_id`.
- `GET /chunks`, `GET /chunks/{id}` — query `l0_chunks` with `event_id`, `processing_stage`, `is_crystal` filters.
- `GET /events/{id}/trace` — pipeline execution trace.
- `GET /extraction-runs`, `GET /extraction-runs/{id}` — run status, token usage, cost.
- Anomaly monitoring via structlog events (`extraction/monitoring.py`).

### Changed

- Core entity types seeded: 10 → 13 (added `task`, `goal`, `north_star`).
- Core predicates seeded: 20 → 21 (added `part_of`).
- `ExtractionRun` status transitions: `pending` → `extracting` → `cortex_complete` → `completed` | `failed`. `mark_failed` is idempotent for terminal states.

## [0.1.0] - 2026-04-07

First foundation release. Establishes the data model, REST API, and deployment infrastructure.

### Added

- **Monorepo** with uv workspaces: `packages/core`, `packages/api`, `packages/cli`, `packages/connectors`
- **Data model** — 18 PostgreSQL tables (7 full + 11 stubs) with Alembic migrations
  - Workspaces, entities, events, entity types, predicate definitions, API keys, entity external IDs
  - Stub tables: relations, claims, tree nodes, vector chunks, audit log, ACL
- **Tenant isolation** — Row-Level Security on 14 workspace-scoped tables with `SET LOCAL app.workspace_id`
- **Composite FK constraints** — `(workspace_id, id)` on parent tables prevents cross-workspace data corruption
- **REST API** — 22 endpoints via FastAPI
  - Health: `/health/live`, `/health/ready` (DB, migrations, seeds, Redis checks)
  - CRUD: workspaces, entities (with soft delete), entity types, predicates, events (idempotent upsert)
  - API keys: create (raw key shown once), list (prefix only), revoke
- **Authentication** — API key auth with `ak_` prefix, SHA-256 hash, 3 scopes (read/write/admin)
- **Error handling** — structured envelope `{"error": {"code", "message", "hint", "docs", "request_id"}}` on every error
- **Cursor-based pagination** — base64-encoded cursors, limit clamped to max 200
- **Repositories** — 7 async repositories with cursor pagination
- **Services** — workspace creation with 10 core entity types + 20 core predicates auto-seeded
- **Docker deployment** — multi-stage Dockerfile (uv builder + slim runtime), docker-compose with PostgreSQL (pgvector:pg17), Redis, Caddy reverse proxy
- **Seed script** — idempotent bootstrap: demo workspace + API key (dev only, guarded by `ALAYA_ENV`)
- **CI** — GitHub Actions with lint, typecheck, unit tests, integration tests (PostgreSQL + Redis services)
- **Tests** — 169 unit tests + 18 integration tests (RLS isolation, composite FK, connection pool leak, import boundaries)
- **Configuration** — ruff (Python 3.13, strict), pyright (strict), `.env.example`

### Known Limitations

- Production deployment requires manual first API key creation (bootstrap disabled by design)
- `alembic check` skipped in CI (model metadata diverges from handwritten migration for composite FK)
- LLM integration, extraction pipeline, search, CLI, connectors, MCP server, and web UI are planned for future runs

## [0.0.0] - 2026-04-06

### Added

- Initial repository setup with BSL 1.1 license
- CLAUDE.md for AI agents and contributors
- CI pipeline (ruff + pyright + pytest)
- Issue and PR templates
- CONTRIBUTING.md, SECURITY.md

[Unreleased]: https://github.com/GoSync-Inc/alaya/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/GoSync-Inc/alaya/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/GoSync-Inc/alaya/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/GoSync-Inc/alaya/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/GoSync-Inc/alaya/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/GoSync-Inc/alaya/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/GoSync-Inc/alaya/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/GoSync-Inc/alaya/releases/tag/v0.1.0
[0.0.0]: https://github.com/GoSync-Inc/alaya/commits/v0.1.0
