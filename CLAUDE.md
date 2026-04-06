# Alaya — AI Agent Instructions

## Project Overview

Alaya is an open-source corporate memory platform. It ingests data from work tools (Slack, GitHub, Linear), extracts structured entities and temporal claims via LLM, organizes them into a browsable knowledge tree, and serves everything through CLI, MCP, and REST API.

**Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 + Pydantic, PostgreSQL + pgvector, Redis, TaskIQ, Anthropic SDK, Typer + Rich

**License:** BSL 1.1 (converts to Apache 2.0 after 3 years)

## Architecture

```
packages/
├── core/          # Brain: models, extraction, consolidation, search, ontology, knowledge tree
├── connectors/    # Source connectors: Slack, GitHub, Linear, webhook
├── cli/           # CLI tool (Typer)
├── api/           # REST API + MCP Server (FastAPI)
└── web/           # Web UI (future)
```

**Data flow:** Sources → L0 Events → Extraction → L1 Entities + L2 Claims → L3 Knowledge Tree → CLI/MCP/API

## Key Design Decisions

- **Model-agnostic**: `LLMServiceInterface` with adapters (Anthropic, OpenAI, Ollama/vLLM). Anthropic is primary, but any provider works.
- **Dynamic ontology**: Core entity types (person, project, task, decision) + user-defined types via API. Entity types stored in DB, not hardcoded enums.
- **L2 Claims**: Atomic facts with provenance, temporal validity, and multi-level reasoning (explicit, deductive, inductive, contradiction).
- **Knowledge Tree**: L3 layer renders entities + claims into browsable markdown. On-demand rebuild with dirty flags.
- **SQLAlchemy 2.0 + Pydantic** (not SQLModel): Full ORM control for complex domain model.
- **TaskIQ + Redis**: Async background jobs for extraction, consolidation, cron.

## Code Conventions

### Language
- All code, comments, variable names: **English**
- Documentation: **English** (public repo)

### Style
- Formatter: `ruff format`
- Linter: `ruff check`
- Type checker: `pyright` (strict mode)
- Package manager: `uv`

### Naming
- `get_*` for reads, `create_*`/`update_*` for writes. Never `fetch_*`, `load_*`, `read_*`, `save_*`.
- Repository pattern: one repository per domain aggregate.
- Pydantic schemas separate from SQLAlchemy models.

### Architecture Rules
- **packages/core/** has ZERO external framework dependencies (no FastAPI, no CLI, no HTTP). Pure domain + business logic.
- **packages/api/** and **packages/cli/** depend on core, never the reverse.
- **packages/connectors/** depend on core interfaces, implement them.
- Business logic never imports from adapters/infrastructure directly. Use interfaces defined in core.

### Testing
- Unit tests: `tests/` in each package
- `pytest` + `pytest-asyncio`
- Mock external services (LLM, DB) in unit tests
- Integration tests use Docker Compose test environment

### Git Workflow
- Branch from `main`: `feat/`, `fix/`, `docs/`, `chore/`
- Small PRs (< 500 lines preferred)
- Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`
- CI must pass before merge

### Security (CRITICAL for open-source)
- **Never commit secrets** (.env, API keys, tokens). Check with `git diff --cached` before committing.
- **Never log secrets**. Use `SecretStr` for all sensitive config values.
- **Validate all external input**. API endpoints, webhook payloads, CLI arguments.
- **SQL injection**: Always use parameterized queries (SQLAlchemy handles this).
- **SSRF**: Validate URLs in webhook/connector configs.

## Internal Planning

Internal planning docs (specs, briefs, master plan) are in `docs/superflow/` — gitignored, not public.
Read these at session start if they exist locally:
1. `docs/superflow/plans/2026-04-07-alayaos-pivot.md` — Master Plan with run breakdown
2. `docs/superflow/specs/2026-04-07-alayaos-pivot-design.md` — Technical Spec
3. `docs/superflow/specs/2026-04-07-alayaos-pivot-brief.md` — Product Brief

## Development Commands

```bash
uv sync                    # Install dependencies
uv run ruff check          # Lint
uv run ruff format         # Format
uv run pyright             # Type check
uv run pytest              # Run tests
docker compose up -d       # Start services (postgres, redis)
docker compose down        # Stop services
```
