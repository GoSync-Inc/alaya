# Alaya — Development Guide

Your primary responsibility is to the project and its users. Write code that is correct, maintainable, and secure.

## Overview

Alaya is an open-source corporate memory platform (BSL 1.1). It ingests data from work tools, extracts structured entities and temporal claims via LLM, and serves them to any AI agent through CLI, MCP, and REST API.

## Stack

Python 3.13 · FastAPI · SQLAlchemy 2.0 + Pydantic · PostgreSQL + pgvector · Redis · TaskIQ · Anthropic SDK · Go (Cobra CLI) · FastEmbed

## Project Structure

```
packages/
├── core/                           # Brain: models, schemas, repositories, services
│   └── alayaos_core/
│       ├── models/                 # SQLAlchemy 2.0 (18 files)
│       ├── schemas/                # Pydantic schemas (15 files)
│       ├── repositories/           # Async repos with cursor pagination (14 files)
│       ├── services/               # workspace (seed), api_key (generate/verify), entity_cache (Redis)
│       ├── extraction/             # Multi-stage intelligence pipeline
│       │   ├── cortex/             # Chunker + classifier (L0 → L0Chunks with domain scores)
│       │   ├── crystallizer/       # LLM extractor + verifier (L0Chunks → claims with confidence tiers)
│       │   ├── integrator/         # Multi-pass KG consolidation: panoramic triage, dedup v2 (composite signal, N=9 batches, merge-with-rewrite), enricher, date normalizer; passes/ subpackage (panoramic.py)
│       │   ├── pipeline.py         # Orchestration: run_extraction, run_write, run_enrich, should_extract
│       │   ├── monitoring.py       # Structlog anomaly detection events
│       │   ├── writer.py           # Atomic persist, dirty-set trigger, workspace lock
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
│       └── routers/                # 14 routers: health, workspaces, entities, claims, chunks, pipeline_traces, integrator_runs, etc.
├── cli/                            # Python CLI placeholder
├── cli-go/                         # Go CLI (Cobra): search, ask, tree, entity, claim, ingest, key, setup agent
└── connectors/                     # Placeholder (Run 5)
alembic/                            # Migrations (001: 18 tables + RLS, 002: auth bypass, 004: intelligence pipeline)
docker/                             # seed.py, init-db.sql, Caddyfile
```

**Data flow:** Sources -> L0 Events -> Cortex (chunk + classify) -> Crystallizer (LLM extract) -> Write (resolve + persist) -> Integrator (dedup + enrich) -> L1 Entities + L2 Claims -> L3 Knowledge Tree -> CLI/MCP/API

## Commands

```bash
uv sync --all-packages --dev     # Install dependencies
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run pyright                   # Type check
uv run pytest                    # Run unit tests
uv run pytest -m integration     # Run integration tests (requires PostgreSQL)
docker compose up -d             # Start all services
docker compose up postgres redis # Start only DB + cache
just check                       # Lint + format + typecheck + tests
just smoke                       # Docker smoke test
taskiq worker alayaos_core.worker.tasks:broker  # Start pipeline worker (job_extract, job_write, job_cortex, job_crystallize, job_enrich, job_integrate, job_check_integrator); on task exception, run transitions to `failed` via ExtractionRunRepository.mark_failed (idempotent for terminal states); at every terminal transition (completed or failed) ExtractionRunRepository.recalc_usage aggregates tokens_in/cost_usd from pipeline_traces — skipped when no traces exist (legacy non-Cortex path writes these fields directly)
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
- `INTEGRATOR_DEDUP_SHORTLIST_K` (default `5`) — max nearest-neighbours per entity in vector-shortlist dedup phase.
- `INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD` (default `0.9`) — minimum cosine similarity to forward a pair to LLM verification; lower values increase recall at the cost of more LLM calls.
- `INTEGRATOR_DEDUP_BATCH_SIZE` (default `9`) — entities per LLM batch in dedup v2 composite-signal pass.
- `CONSOLIDATOR_PANORAMIC_MAX_ENTITIES` (default `500`) — entity cap for the panoramic triage pass; configurable via constructor param.

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

## API Endpoints (43 total)

Health: `/health/live`, `/health/ready`
Workspaces: POST, GET, GET/{id}, PATCH/{id} — bootstrap key required for create
Entities: POST, GET, GET/{id}, PATCH/{id}, DELETE/{id} — soft delete
Entity Types: GET, POST, GET/{id}
Predicates: GET, GET/{id} — read-only in Run 1
Events: POST (idempotent upsert), GET, GET/{id}
API Keys: POST (raw key once), GET (prefix only), DELETE/{prefix} (revoke)
Claims: GET, GET/{id}, GET (by entity)
Relations: GET, GET/{id}
Extraction Runs: GET, GET/{id}
Ingestion: POST `/ingest` — trigger extraction pipeline
Chunks: GET (event_id, processing_stage, is_crystal filters), GET/{id}
Pipeline Traces: GET /events/{id}/trace
Integrator Runs: GET, GET/{id}, POST /trigger
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
- `AnthropicAdapter`: Production provider (Haiku for classification, Sonnet for extraction/integration); coerces JSON-string values for top-level `list[...]` / `list[...] | None` fields before Pydantic validation (`_coerce_list_strings` in `llm/anthropic.py`)
- `FakeLLMAdapter`: Deterministic test responses with domain-specific overrides
Config: per-stage model selection via `CORTEX_CLASSIFIER_MODEL`, `CRYSTALLIZER_MODEL`, `INTEGRATOR_MODEL`.
Provider-specific features preserved — no lowest common denominator.

<!-- updated-by-superflow:2026-04-16 -->
