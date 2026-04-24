"""Container smoke test — verifies the testcontainers harness is working."""

import pytest
from sqlalchemy import text


@pytest.mark.integration
async def test_pgvector_present(engine) -> None:
    """pgvector extension must be installed after alembic upgrade head."""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        extversion = result.scalar()
    assert extversion is not None, "pgvector extension not found — alembic migrations may not have run"
