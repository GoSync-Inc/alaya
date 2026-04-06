# Alaya — Development Guide

Your primary responsibility is to the project and its users. Write code that is correct, maintainable, and secure.

## Overview

Alaya is an open-source corporate memory platform (BSL 1.1). It ingests data from work tools, extracts structured entities and temporal claims via LLM, and serves them to any AI agent through CLI, MCP, and REST API.

## Stack

Python 3.13 · FastAPI · SQLAlchemy 2.0 + Pydantic · PostgreSQL + pgvector · Redis · TaskIQ · Anthropic SDK · Typer + Rich

## Project Structure

```
packages/
├── core/                           # Brain: models, schemas, repositories, services
│   └── alayaos_core/
│       ├── models/                 # SQLAlchemy 2.0 (13 files: 7 full + 6 stubs)
│       ├── schemas/                # Pydantic schemas (7 files)
│       ├── repositories/           # Async repos with cursor pagination (7 files)
│       ├── services/               # workspace (seed), api_key (generate/verify)
│       └── config.py               # pydantic-settings (DATABASE_URL, REDIS_URL, ENV)
├── api/                            # REST API (FastAPI)
│   └── alayaos_api/
│       ├── main.py                 # App factory + lifespan
│       ├── deps.py                 # Auth, session, scope dependencies
│       ├── middleware.py           # Error envelope, request ID
│       └── routers/                # 7 routers: health, workspaces, entities, etc.
├── cli/                            # Placeholder (Run 4)
└── connectors/                     # Placeholder (Run 5)
alembic/                            # Migrations (001: 18 tables + RLS, 002: auth bypass)
docker/                             # seed.py, init-db.sql, Caddyfile
```

**Data flow:** Sources -> L0 Events -> Extraction -> L1 Entities + L2 Claims -> L3 Knowledge Tree -> CLI/MCP/API

## Commands

```bash
uv sync                          # Install dependencies
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run pyright                   # Type check
uv run pytest                    # Run unit tests
uv run pytest -m integration     # Run integration tests (requires PostgreSQL)
docker compose up -d             # Start all services
docker compose up postgres redis # Start only DB + cache
```

## Verification

Run before every commit:

| Changed | Run |
|---------|-----|
| Any Python file | `uv run ruff check . && uv run ruff format --check .` |
| Type-sensitive code | `uv run pyright` |
| Logic changes | `uv run pytest` |
| All of the above | `uv run ruff check . && uv run pyright && uv run pytest` |

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

## Code Conventions

- **Naming:** `get_*` for reads, `create_*`/`update_*` for writes. Never `fetch_*`, `load_*`, `save_*`.
- **Commits:** Conventional format — `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`
- **PRs:** Small and focused (< 500 lines preferred). One logical change per PR.
- **Tests:** Every new function gets a test. Mock external services. Use `pytest-asyncio` for async.
- **Error envelope:** All API errors return `{"error": {"code", "message", "hint", "docs", "request_id"}}`.
- **`metadata` column:** SQLAlchemy uses `event_metadata`/`claim_metadata` (Python attr) -> `metadata` (DB column).

## Data Model

18 tables: 7 full (workspace, event, entity, entity_type, predicate, entity_external_id, api_key) + 11 stubs.
Core predicates: 20 seeded per workspace (deadline, status, owner, role, title, member_of, reports_to, etc.)
Core entity types: 10 seeded per workspace (person, project, team, document, decision, meeting, etc.)

## API Endpoints (22 total)

Health: `/health/live`, `/health/ready`
Workspaces: POST, GET, GET/{id}, PATCH/{id} — bootstrap key required for create
Entities: POST, GET, GET/{id}, PATCH/{id}, DELETE/{id} — soft delete
Entity Types: GET, POST, GET/{id}
Predicates: GET, GET/{id} — read-only in Run 1
Events: POST (idempotent upsert), GET, GET/{id}
API Keys: POST (raw key once), GET (prefix only), DELETE/{prefix} (revoke)

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
Config: `EXTRACTION_LLM_PROVIDER=anthropic|openai|ollama|vllm`
Provider-specific features preserved — no lowest common denominator.

<!-- updated-by-superflow:2026-04-07 -->
