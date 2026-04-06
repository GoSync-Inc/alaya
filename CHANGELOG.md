# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/GoSync-Inc/alaya/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/GoSync-Inc/alaya/releases/tag/v0.1.0
[0.0.0]: https://github.com/GoSync-Inc/alaya/commits/v0.1.0
