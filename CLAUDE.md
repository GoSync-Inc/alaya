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
alembic/                            # Migrations 001-008 (001: 18 tables + RLS, 002: auth bypass, 003: extraction schema, 004: intelligence pipeline, 005a/005b: search indexes, 006: consolidator schema, 007: multi-tenant hardening, 008: ACL propagation)
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

## API Endpoints (45 total)

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
Integrator Runs: GET, GET/{id}, POST /trigger
Integrator Actions: GET /integrator-actions, POST /integrator-actions/{id}/rollback
Admin: GET /admin/flags, POST /admin/backfill-embeddings
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
- `AnthropicAdapter`: Production provider (Haiku for classification, Sonnet for extraction/integration); coerces JSON-string values for top-level `list[...]` / `list[...] | None` fields before Pydantic validation (`_coerce_list_strings` in `llm/anthropic.py`)
- `FakeLLMAdapter`: Deterministic test responses with domain-specific overrides
Config: per-stage model selection via `CORTEX_CLASSIFIER_MODEL`, `CRYSTALLIZER_MODEL`, `INTEGRATOR_MODEL`.
Provider-specific features preserved — no lowest common denominator.

## Scripts

- `scripts/audit_part_of_hierarchy.py` — read-only preflight audit: `--workspace-id <uuid> [--sample-size N]`; exit 0 = clean, exit 1 = violations found with sample rows.
- `scripts/bench.py` — bench harness: spins up a stack, ingests fixtures (small/medium/large), measures extraction latency, LLM cost, entity/claim counts; outputs JSON reports to `bench_results/`.
- `scripts/bench_report.py` — reads bench result JSON and renders a Markdown comparison table across runs.

<!-- updated-by-superflow:2026-04-25 -->
