# Alaya — Development Guide

Your primary responsibility is to the project and its users. Write code that is correct, maintainable, and secure.

## Overview

Alaya is an open-source corporate memory platform (BSL 1.1). It ingests data from work tools, extracts structured entities and temporal claims via LLM, and serves them to any AI agent through CLI, MCP, and REST API.

## Stack

Python 3.13 · FastAPI · SQLAlchemy 2.0 + Pydantic · PostgreSQL + pgvector · Redis · TaskIQ · Anthropic SDK · Typer + Rich

## Project Structure

```
packages/
├── core/          # Brain: models, extraction, consolidation, search, ontology
├── connectors/    # Source connectors: Slack, GitHub, Linear, webhook
├── cli/           # CLI tool (Typer + Rich)
├─��� api/           # REST API (FastAPI) + MCP Server
└── web/           # Web UI (future)
```

**Data flow:** Sources → L0 Events → Extraction → L1 Entities + L2 Claims → L3 Knowledge Tree → CLI/MCP/API

## Commands

```bash
uv sync                          # Install dependencies
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run pyright                   # Type check
uv run pytest                    # Run tests
docker compose up -d             # Start services (postgres, redis)
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

## Code Conventions

- **Naming:** `get_*` for reads, `create_*`/`update_*` for writes. Never `fetch_*`, `load_*`, `save_*`.
- **Commits:** Conventional format — `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`
- **PRs:** Small and focused (< 500 lines preferred). One logical change per PR.
- **Tests:** Every new function gets a test. Mock external services. Use `pytest-asyncio` for async.

## LLM Architecture

Model-agnostic: `LLMServiceInterface` with provider adapters.

- **Anthropic** (primary): prompt caching, structured output, extended thinking
- **OpenAI**: native response_format, reasoning effort
- **Ollama/vLLM** (local): OpenAI-compatible API, JSON fallback + retry

Config: `EXTRACTION_LLM_PROVIDER=anthropic|openai|ollama|vllm`

Provider-specific features are preserved — no lowest common denominator.

## Security (CRITICAL)

- **Never commit secrets.** All `.env` files are gitignored. Use `SecretStr` for sensitive config.
- **Validate all external input.** API endpoints, webhook payloads, CLI arguments.
- **SQL injection:** Always parameterized queries (SQLAlchemy handles this).
- **SSRF:** Validate URLs in webhook/connector configs.
- If you see a secret in code or logs — flag it immediately.
