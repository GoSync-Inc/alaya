"""RLS connection pool leak tests."""

import pytest
from sqlalchemy import text


@pytest.mark.integration
async def test_set_local_does_not_persist_across_transactions(engine):
    """SET LOCAL must not persist across transactions on same pooled connection."""
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SET LOCAL app.workspace_id = '00000000-0000-0000-0000-000000000001'"))
        # Transaction ended, SET LOCAL should be gone

        async with conn.begin():
            result = await conn.execute(text("SELECT current_setting('app.workspace_id', true)"))
            value = result.scalar()
            assert value is None or value == "", "SET LOCAL leaked across transactions"


@pytest.mark.integration
async def test_set_local_clears_after_rollback(engine):
    """SET LOCAL should clear after rolled-back transaction."""
    async with engine.connect() as conn:
        try:
            async with conn.begin():
                await conn.execute(
                    text("SET LOCAL app.workspace_id = :wid"),
                    {"wid": "00000000-0000-0000-0000-000000000001"},
                )
                raise RuntimeError("deliberate rollback")
        except RuntimeError:
            pass

        async with conn.begin():
            result = await conn.execute(text("SELECT current_setting('app.workspace_id', true)"))
            value = result.scalar()
            assert value is None or value == "", "SET LOCAL leaked after rollback"
