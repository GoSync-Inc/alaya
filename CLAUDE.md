# Alaya — Development Guide

Your primary responsibility is to the project and its users. Write code that is correct, maintainable, and secure.

## Overview

Alaya is an open-source corporate memory platform (BSL 1.1). It ingests data from work tools, extracts structured entities and temporal claims via LLM, and serves them to any AI agent through CLI, MCP, and REST API.

## Stack

Python 3.13 · FastAPI · SQLAlchemy 2.0 + Pydantic · PostgreSQL + pgvector · Redis · TaskIQ · Anthropic SDK · Go (Cobra CLI) · FastEmbed · dateparser + python-dateutil

## Project Structure

```
packages/
├── core/                           # Brain: models, schemas, repositories, services
│   └── alayaos_core/
│       ├── models/                 # SQLAlchemy 2.0 (19 files)
│       ├── schemas/                # Pydantic schemas (17 files)
│       ├── repositories/           # Async repos with cursor pagination (17 files)
│       ├── services/               # workspace (seed), api_key (generate/verify), entity_cache (Redis)
│       ├── extraction/             # Multi-stage intelligence pipeline
│       │   ├── cortex/             # Chunker + classifier (L0 → L0Chunks with domain scores)
│       │   ├── crystallizer/       # LLM extractor + verifier (L0Chunks → claims with confidence tiers)
│       │   ├── integrator/         # Multi-pass KG consolidation: panoramic triage, dedup v2 (composite signal, N=9 batches, merge-with-rewrite), enricher; passes/ subpackage (panoramic.py)
│       │   ├── date_normalizer.py  # Shared DateNormalizer + NormalizedDate payload for writer/integrator date claims
│       │   ├── pipeline.py         # Orchestration: run_extraction, run_write, run_enrich, should_extract
│       │   ├── monitoring.py       # Structlog anomaly detection events
│       │   ├── writer.py           # Atomic persist, date-claim normalization, dirty-set trigger, workspace lock
│       │   ├── resolver.py         # 3-tier entity resolution with transliteration
│       │   ├── sanitizer.py        # Input sanitization (NFKC, injection detection)
│       │   └── schemas.py          # ExtractionResult, ExtractedEntity, ExtractedClaim
│       ├── llm/                    # LLMServiceInterface + Anthropic/Fake adapters
│       ├── worker/                 # TaskIQ broker + multi-job pipeline tasks
│       └── config.py               # pydantic-settings (DATABASE_URL, REDIS_URL, ENV)
├── api/                            # REST API (FastAPI)
│   └── alayaos_api/
│       ├── main.py                 # App factory + lifespan
│       ├── deps.py                 # Auth, session, scope dependencies
│       ├── middleware.py           # Error envelope, request ID
│       └── routers/                # 18 routers: health, workspaces, entities, claims, chunks, pipeline_traces, integrator_runs, integrator_actions, search, ask, tree, etc.
├── cli-go/                         # Go CLI (Cobra): search, ask, tree, entity, claim, ingest, key, setup agent
└── connectors/                     # Source connectors (placeholder)
alembic/                            # Migrations 001-009 (001: 18 tables + RLS, 002: auth bypass, 003: extraction schema, 004: intelligence pipeline, 005a/005b: search indexes, 006: consolidator schema, 007: multi-tenant hardening, 008: ACL propagation, 009: granular token columns + integrator_run_id FK on pipeline_traces)
docker/                             # seed.py, init-db.sql, Caddyfile
```

**Data flow:** Sources -> L0 Events -> Cortex (chunk + classify) -> Crystallizer (LLM extract) -> Write (resolve + normalize date claims + persist) -> Integrator (dedup + enrich) -> L1 Entities + L2 Claims -> L3 Knowledge Tree -> CLI/MCP/API. Writer date claim JSONB is `{date, iso, normalized, anchor, reason}`; when a post-create date normalization failure leaves `reason` set, writer logs `claim.date_normalize_failed`.

## Current Focus

See `docs/ROADMAP.md` for the active phase and next runs. New agent sessions should read the roadmap before picking up work.

## Commands

```bash
uv sync --all-packages --dev     # Install dependencies
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run pyright                   # Type check
uv run pytest                    # Run unit tests
uv run pytest -m integration     # Run integration tests (requires Docker — testcontainers spawns ephemeral postgres)
docker compose up -d             # Start all services
docker compose up postgres redis # Start only DB + cache
just check                       # Lint + format + typecheck + tests
just smoke                       # Docker smoke test
just bench [ARGS]                # Run bench harness against a live stack (scripts/bench.py); supports --fixture, --keep, --reuse, --timeout-seconds
just logs-llm                    # Stream LLM call events from worker logs (requires jq)
just bench-clean                 # Remove bench result directories (preserves .gitkeep)
taskiq worker alayaos_core.worker.tasks:broker  # Start pipeline worker (job_extract, job_write, job_cortex, job_crystallize, job_enrich, job_integrate, job_feature_flag_digest, job_check_integrator); on task exception, run transitions to `failed` via ExtractionRunRepository.mark_failed (idempotent for terminal states); at every terminal transition (completed or failed) ExtractionRunRepository.recalc_usage aggregates tokens_in/cost_usd from pipeline_traces — skipped when no traces exist (legacy non-Cortex path writes these fields directly)
```

## Verification

Run before every commit:

| Changed | Run |
|---------|-----|
| Any Python file | `uv run ruff check . && uv run ruff format --check .` |
| Type-sensitive code | `uv run pyright` |
| Logic changes | `uv run pytest` |
| All of the above | `uv run ruff check . && uv run pyright && uv run pytest` |

## Production Config Notes

- `ALAYA_API_DOCS_ENABLED` defaults to disabled in production when unset.
- `ALAYA_TRUSTED_HOSTS` should be configured to the public hostnames served by ingress/Caddy, unless host validation is enforced upstream.
- `/health/ready` checks database, migrations, seeds, and Redis; Redis uses bounded async ping and reports `ok`, `down`, or `degraded` in verbose readiness output.
- `INTEGRATOR_DEDUP_SHORTLIST_K` (default `5`) — max nearest-neighbours per entity in vector-shortlist dedup phase.
- `INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD` (default `0.9`) — minimum cosine similarity to forward a pair to LLM verification; lower values increase recall at the cost of more LLM calls.
- `INTEGRATOR_DEDUP_BATCH_SIZE` (default `9`) — entities per LLM batch in dedup v2 composite-signal pass.
- `ASK_RATE_LIMIT_PER_MINUTE` (default `10`) / `ASK_RATE_LIMIT_PER_HOUR` (default `100`) — rate limits for `/ask` and `/search`; enforced fail-closed (503 when Redis is unavailable).
- `ALAYA_PART_OF_STRICT` (default `strict`, values `strict|warn|off`) — controls `part_of` tier-rank validation only; non-default values emit `feature_flag_active` at API startup and in `job_feature_flag_digest`. Self-reference remains always rejected.
- `SECRET_KEY` — must be set to a strong random value in production; defaults to `"change-me-in-production"` which is insecure.
- `BENCH_TIMEOUT_SECONDS` (default `600`) — global wall-clock budget for `just bench`; bench-only, no effect on the production stack.
- pgvector `>= 0.8.0` is required. Migration 008, API lifespan startup, Docker init, and CI all fail fast if the installed extension is older.
- Run 6.2 restricted/private-event backfill command: `uv run python -m alayaos_core.scripts.backfill_restricted_extraction --workspace-id <uuid> --dry-run`, then rerun with `--apply` after reviewing the count.

## Architecture Rules

1. **`packages/core/`** has ZERO framework dependencies. No FastAPI, no HTTP, no CLI. Pure domain + business logic.
2. **`packages/api/`** and **`packages/cli/`** depend on core, never the reverse.
3. **`packages/connectors/`** implement interfaces defined in core.
4. Business logic never imports from infrastructure directly — use interfaces.
5. SQLAlchemy models and Pydantic schemas are separate (no SQLModel).
6. **Tenant isolation via RLS** — `SET LOCAL app.workspace_id` on every request. 14 tables have RLS policies.
7. **Composite FK** — `(workspace_id, id)` on parent tables prevents cross-workspace references.
8. **No `session.commit()` in repositories** — commit at service/endpoint level only.
9. **Cursor-based pagination only** — no offset/page. Limit clamped to max 200.
10. **LLM output = untrusted user input.** All LLM responses pass through Pydantic schema validation before persistence. Never trust raw LLM text.
11. **All relation writes are self-reference-rejected** — `RelationRepository._reject_self_reference` enforces this universally in `create()` and `create_batch()`; raises `HierarchyViolationError` (`repositories/errors.py`).
12. **`part_of` relations are ENTITY_TYPE_TIER_RANK-enforced by default** — `_validate_part_of_tier` prevents downward or lateral containment when `ALAYA_PART_OF_STRICT=strict`; `warn` logs `part_of.tier_violation` and persists, `off` skips tier-rank validation. Callers (writer, panoramic, enrichment) each catch `HierarchyViolationError`, log a named structured event, and continue (best-effort — never abort the batch).
13. **Merge rollback is schema-versioned.** `IntegratorActionRepository._rollback_merge` branches on `snapshot_schema_version`: v1 restores only `is_deleted=False` (legacy partial); v2 performs full FK reversal, per-ID conflict detection, and winner-metadata restore from `inverse["winner_before"]`.
14. **Run 6.2 access semantics:** `channel` events extract identically to public and are tier 1 at retrieval; `restricted` events now extract and rely on retrieval ACL via `vector_chunks.access_level` and `claim_effective_access`; `private` events remain workspace opt-in gated.

## Code Conventions

- **Naming:** `get_*` for reads, `create_*`/`update_*` for writes. Never `fetch_*`, `load_*`, `save_*`.
- **Commits:** Conventional format — `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`
- **PRs:** Small and focused (< 500 lines preferred). One logical change per PR.
- **Tests:** Every new function gets a test. Mock external services. Use `pytest-asyncio` for async.
- **Error envelope:** All API errors return `{"error": {"code", "message", "hint", "docs", "request_id"}}`.
- **`metadata` column:** SQLAlchemy uses `event_metadata`/`claim_metadata` (Python attr) -> `metadata` (DB column).

## Data Model

23 tables: 7 full (workspace, event, entity, entity_type, predicate, entity_external_id, api_key) + 11 stubs + extraction_run + l0_chunks + pipeline_traces + integrator_runs + integrator_actions.
Core predicates: 21 seeded per workspace (deadline, status, owner, role, title, member_of, reports_to, part_of, etc.)
Core entity types: 13 seeded per workspace (person, project, team, document, decision, meeting, task, goal, north_star, etc.)
Claims and relations carry `extraction_run_id` for full provenance tracing.
`integrator_actions.snapshot_schema_version` (int, default 1) — audit payload format version; v2 actions carry additive `inverse` fields enabling full FK + winner-metadata reversal on rollback.
Access propagation: `l0_events.access_level` is authoritative; `vector_chunks.access_level` is denormalized for pgvector/HNSW filtering and restamped by migration 008 triggers. Missing provenance falls closed to `restricted` for source-less claims and entity vectors without sourced claims. `claim_effective_access` is a non-materialized read-only view that computes most-restrictive claim visibility from `claim_sources`, with source-less claims defaulting to restricted. Request context sets `app.allowed_access_levels` from API key scopes (`read` = public/channel, `write` adds private, `admin` adds restricted); ACL-filtered list, search, and ask responses include `meta.filtered_count` and `meta.filter_reason`.
Migration 009 (`alembic/versions/009_pipeline_traces_token_classes.py`) adds to `pipeline_traces`: `tokens_in`, `tokens_out`, `tokens_cached`, `cache_write_5m_tokens`, `cache_write_1h_tokens` (all INT NOT NULL default 0); `integrator_run_id UUID nullable` with composite FK to `integrator_runs(workspace_id, id)`; drops NOT NULL on `event_id`; adds partial index `idx_pipeline_traces_integrator_run_id`; adds CHECK `(event_id IS NOT NULL OR extraction_run_id IS NOT NULL OR integrator_run_id IS NOT NULL)`.

## API Endpoints (46 total)

Health: `/health/live`, `/health/ready`
Workspaces: POST, GET, GET/{id}, PATCH/{id} — bootstrap key required for create
Entities: POST, GET, GET/{id}, PATCH/{id}, DELETE/{id} — soft delete
Entity Types: GET, POST, GET/{id}
Predicates: GET, GET/{id} — read-only in Run 1
Events: POST (idempotent upsert), GET, GET/{id}
API Keys: POST (raw key once), GET (prefix only), DELETE/{prefix} (revoke)
Claims: GET (supports entity filter), GET/{id}, PATCH/{id}
Relations: GET, GET/{id}
Extraction Runs: GET, GET/{id}
Ingestion: POST `/ingest/text` — trigger extraction pipeline
Admin: GET /admin/flags, POST /admin/backfill-embeddings — bootstrap-admin feature flag state and embedding maintenance
Chunks: GET (event_id, processing_stage, is_crystal filters), GET/{id}
Pipeline Traces: GET /events/{id}/trace
Integrator Runs: GET, GET/{id}, POST /trigger, GET /{id}/trace — per-integrator-run pipeline trace list (granular token columns, integrator_run_id set, event_id=None)
Integrator Actions: GET /integrator-actions, POST /integrator-actions/{id}/rollback
Search: POST /search — hybrid 3-channel RRF (vector + FTS + entity name)
Ask: POST /ask — LLM Q&A with citation validation
Tree: GET /tree, GET /tree/{path}, POST /tree/export

## Security (CRITICAL)

- **Never commit secrets.** All `.env` files are gitignored. Use `SecretStr` for sensitive config.
- **Validate all external input.** API endpoints, webhook payloads, CLI arguments.
- **SQL injection:** Always parameterized queries (SQLAlchemy handles this).
- **SSRF:** Validate URLs in webhook/connector configs.
- **API keys:** `ak_` prefix, SHA-256 hash, prefix-based O(1) lookup. Raw key shown once on create.
- **RLS:** `FORCE ROW LEVEL SECURITY` on all workspace-scoped tables except `api_keys` (auth bootstrap).
- If you see a secret in code or logs — flag it immediately.

## LLM Architecture (Run 2+)

Model-agnostic: `LLMServiceInterface` with provider adapters.
- `AnthropicAdapter`: Production provider (Haiku for classification, Sonnet for extraction/integration); coerces JSON-string values for top-level `list[...]` / `list[...] | None` fields before Pydantic validation (`_coerce_list_strings` in `llm/anthropic.py`); populates granular token classes (`tokens_in`, `tokens_out`, `tokens_cached`, `cache_write_5m_tokens`, `cache_write_1h_tokens`) from Anthropic usage objects; uses `llm/pricing.py` single source for model cost math; emits `llm.call_completed` after every API call.
- `FakeLLMAdapter`: Deterministic test responses with domain-specific overrides; emits `llm.call_completed` with `model="fake"`, `latency_ms=0`.
- `LLMServiceInterface.extract()` accepts `stage: str = "unknown"` kwarg for pipeline trace labeling. Every call site must pass a meaningful stage string (e.g. `"cortex:classify"`, `"crystallizer:extract"`, `"integrator:enricher"`, `"ask:answer"`, `"tree:briefing"`).
- `LLMUsage` has `total_input` and `cache_hit_ratio` properties.
Config: per-stage model selection via `CORTEX_CLASSIFIER_MODEL`, `CRYSTALLIZER_MODEL`, `INTEGRATOR_MODEL`.
Provider-specific features preserved — no lowest common denominator.
`IntegratorEngine.run()` never raises — always returns `IntegratorRunResult` (status: `completed`/`failed`/`skipped`). Phase failures are caught per savepoint; partial `phase_usages` from completed phases are preserved in the result. `job_integrate` writes one `PipelineTrace` per `IntegratorPhaseUsage` (with `integrator_run_id` set, `event_id=None`) then calls `recalc_usage()`. `GET /integrator-runs/{id}/trace` exposes these traces with granular token columns.

## LLM Observability Events (structlog only — no Prometheus/OpenTelemetry)

All events emitted by `packages/core/alayaos_core/llm/observability.py` via `structlog.get_logger("alayaos.llm")`:

- `llm.call_completed` — after every LLM API call. Fields: `model`, `stage`, `latency_ms`, `tokens_in`, `tokens_out`, `tokens_cached`, `cache_write_5m_tokens`, `cache_write_1h_tokens`, `total_input`, `cache_hit_ratio`, `cost_usd`. Emitted by `AnthropicAdapter` and `FakeLLMAdapter`; flows naturally from `FallbackLLMAdapter` through the inner adapter.
- `llm.run_aggregated` — after `recalc_usage()` at terminal extraction/integrator run. Fields: `scope` ("extraction"|"integrator"), `run_id`, `workspace_id`, `tokens_in`, `tokens_out`, `tokens_cached`, `cache_write_5m_tokens`, `cache_write_1h_tokens`, `cost_usd`, `tokens_used`, `total_input`, `cache_hit_ratio`, optional `stage_breakdown`. Emitted by `ExtractionRunRepository.recalc_usage` and `IntegratorRunRepository.recalc_usage`.
- `llm.cache_miss_below_threshold` — warning emitted when `total_input < MODEL_CACHE_MINIMUM[model]` (prompt too small to benefit from caching). Fields: `model`, `stage`, `total_input`, `minimum`. Silenced for the fake adapter (no `"fake"` key in `MODEL_CACHE_MINIMUM`). For `cortex:classify` / `cortex:verify` this alarm should never fire: the classifier system prompt is padded to >= 4200 estimator tokens (>= 16800 chars) via `packages/core/alayaos_core/extraction/cortex/prompts.py` (`CANONICAL_EXAMPLES_BLOCK`), giving Haiku 4.5 sufficient prompt mass to enter cache (minimum 4096 tokens). The CI regression guard is `packages/core/tests/test_cortex_prompt_size.py`. Note: the padding approach uses a CI-time size test + S3 runtime alarm as the enforcement gate — not a startup guard.
- `llm.cache_breakdown_unavailable` — warning emitted once per process per model when the Anthropic `cache_creation` nested object is absent. Uses module-level `_cache_breakdown_warned: set[str]` guard in `observability.py`; reset in tests via `monkeypatch.setattr(observability, "_cache_breakdown_warned", set())`.

## Scripts

- `scripts/audit_part_of_hierarchy.py` — read-only preflight audit: `--workspace-id <uuid> [--sample-size N]`; exit 0 = clean, exit 1 = violations found with sample rows.
- `scripts/bench.py` — bench harness: spins up a stack, ingests fixtures (small/medium/large), measures extraction latency, LLM cost, entity/claim counts; outputs JSON reports to `bench_results/`. Flags: `--fixture`, `--keep`, `--reuse`, `--timeout-seconds`, `--cache-warm-check` (runs bench twice: warm-up + measurement; asserts cortex `cache_hit_ratio > 0.5`; exits 7 on failure — `EXIT_CACHE_WARM_FAIL = 7`).
- `scripts/bench_report.py` — DB query module called by `bench.py` during the report phase; queries `extraction_runs`, `integrator_runs`, and `pipeline_traces` (including granular token columns) for the bench workspace; returns a single-run Markdown summary (latency, cost, quality proxies, `cache_hit_ratio` per stage) plus the JSON-serialisable manifest data with `cache_hit_ratio_per_stage` block.
- `scripts/sanitize_corpus.py` — PII sanitizer for production Slack JSONL exports: replaces Slack IDs, emails, phones, URLs, person names (spaCy NER), company name, and shifts timestamps; halts on secret patterns (API keys, JWTs). Run `uv run python scripts/sanitize_corpus.py --help` for options. See `docs/operations/sanitize-corpus.md` for the full operator procedure including pull, sanitize, and verification steps.

<!-- updated-by-superflow:2026-04-25 -->
