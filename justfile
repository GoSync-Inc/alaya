# Alaya development workflows

set dotenv-load

# Install all dependencies
install:
    uv sync --all-packages --dev

# Run linter
lint:
    uv run ruff check .

# Fix lint issues
lint-fix:
    uv run ruff check --fix .

# Check formatting
fmt-check:
    uv run ruff format --check .

# Format code
fmt:
    uv run ruff format .

# Run type checker
typecheck:
    uv run pyright

# Run unit tests
test:
    uv run pytest -m "not integration" --tb=short

# Run integration tests (requires PostgreSQL)
test-integration:
    uv run pytest -m integration --tb=short

# Run all checks (lint + format + typecheck + tests)
check: lint fmt-check typecheck test

# Start database services
db-up:
    docker compose up -d postgres redis

# Run database migrations
db-migrate:
    uv run alembic upgrade head

# Stop database services
db-down:
    docker compose down

# Build Docker image
build:
    docker compose build

# Start all services
up:
    docker compose up -d

# Stop all services
down:
    docker compose down

# View service logs
logs *args:
    docker compose logs {{ args }}

# Start dev server
serve:
    uv run uvicorn alayaos_api.main:app --reload --host 0.0.0.0 --port 8000

# Run smoke test
smoke:
    bash scripts/smoke-test.sh
