# syntax=docker/dockerfile:1

# --- Builder stage ---
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies (workspace packages need at least __init__.py for uv to resolve)
COPY pyproject.toml uv.lock ./
COPY packages/ packages/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev
COPY alembic/ alembic/
COPY alembic.ini .
COPY docker/seed.py docker/seed.py

# --- Runtime stage ---
FROM python:3.13-slim-bookworm

RUN groupadd --gid 999 alaya && \
    useradd --uid 999 --gid 999 --create-home alaya

WORKDIR /app

# Copy virtual environment and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages /app/packages
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/docker /app/docker

ENV PATH="/app/.venv/bin:$PATH"

USER alaya

EXPOSE 8000

CMD ["uvicorn", "alayaos_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
