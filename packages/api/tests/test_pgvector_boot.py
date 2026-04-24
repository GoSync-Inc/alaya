"""Boot-time pgvector version checks."""

import pytest
from fastapi import FastAPI


def test_assert_pgvector_min_version_rejects_missing_or_old_versions() -> None:
    from alayaos_api.main import _assert_pgvector_min_version

    _assert_pgvector_min_version("0.8.0")
    _assert_pgvector_min_version("0.10.1")

    with pytest.raises(RuntimeError, match="pgvector extension is not installed"):
        _assert_pgvector_min_version(None)

    with pytest.raises(RuntimeError, match=r"pgvector >= 0\.8\.0 is required"):
        _assert_pgvector_min_version("0.7.4")


@pytest.mark.asyncio
async def test_lifespan_validates_pgvector_before_serving(monkeypatch) -> None:
    import alayaos_api.main as main

    class FakeEngine:
        async def dispose(self) -> None:
            pass

    fake_engine = FakeEngine()
    seen: list[object] = []

    async def fake_validate_pgvector(engine) -> None:
        seen.append(engine)

    monkeypatch.setattr(main, "create_async_engine", lambda *args, **kwargs: fake_engine)
    monkeypatch.setattr(main, "_validate_pgvector_extension", fake_validate_pgvector)

    async with main.lifespan(FastAPI()):
        pass

    assert seen == [fake_engine]
