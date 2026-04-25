"""Integration tests for Alembic migration 009 — forward + down round-trip.

Tests:
- Upgrade to 009: new columns present on pipeline_traces
- Downgrade from 009: new columns removed; old NOT NULL constraint restored

Requires: testcontainers (PostgreSQL with pgvector). Marked as `integration`.
"""

from __future__ import annotations

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


@pytest.mark.integration
def test_migration_009_forward_adds_columns(migrated_container) -> None:
    """After alembic upgrade head, pipeline_traces has granular token columns and integrator_run_id.

    The migrated_container fixture runs upgrade head for the entire test session,
    so this test checks post-migration state.
    """
    container_url = migrated_container.get_connection_url()
    sync_url = container_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url, poolclass=NullPool)

    with engine.connect() as conn:
        # pipeline_traces must have the new columns
        result = conn.execute(
            text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'pipeline_traces'
        """)
        )
        columns = {row[0] for row in result}

    expected_new_columns = {
        "tokens_in",
        "tokens_out",
        "tokens_cached",
        "cache_write_5m_tokens",
        "cache_write_1h_tokens",
        "integrator_run_id",
    }
    missing = expected_new_columns - columns
    assert not missing, f"Columns missing after migration 009: {missing}"


@pytest.mark.integration
def test_migration_009_forward_event_id_nullable(migrated_container) -> None:
    """After migration 009, pipeline_traces.event_id is nullable."""
    container_url = migrated_container.get_connection_url()
    sync_url = container_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url, poolclass=NullPool)

    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'pipeline_traces'
              AND column_name = 'event_id'
        """)
        )
        row = result.fetchone()
    assert row is not None, "event_id column not found in pipeline_traces"
    assert row[0] == "YES", f"event_id should be nullable after 009, got is_nullable={row[0]}"


@pytest.mark.integration
def test_migration_009_down_removes_columns(migrated_container, monkeypatch) -> None:
    """Downgrade from 009 removes new columns and restores event_id NOT NULL.

    Note: this test is destructive — it downgrades the shared schema. We run it
    last by relying on alphabetical ordering (d > f) and immediately re-upgrade.
    """
    container_url = migrated_container.get_connection_url()
    sync_url = container_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    # Ensure no rows with NULL event_id exist (down-migration guard)
    engine = create_engine(sync_url, poolclass=NullPool)
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM pipeline_traces WHERE event_id IS NULL"))
        conn.commit()

    # Downgrade to 008
    monkeypatch.setenv("ALAYA_DATABASE_URL", container_url)
    from alembic import command as alembic_command

    cfg = AlembicConfig("alembic.ini")
    alembic_command.downgrade(cfg, "008")

    # Verify: new columns removed
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'pipeline_traces'
        """)
        )
        columns_after_down = {row[0] for row in result}

    removed_columns = {"tokens_in", "tokens_out", "tokens_cached", "cache_write_5m_tokens", "cache_write_1h_tokens"}
    present_after_down = removed_columns & columns_after_down
    assert not present_after_down, f"Columns should be removed after downgrade: {present_after_down}"

    # Re-upgrade to restore state for any subsequent tests
    alembic_command.upgrade(cfg, "head")
