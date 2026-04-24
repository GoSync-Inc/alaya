"""Vector chunk ACL propagation tests."""

from __future__ import annotations

import uuid

import pytest


class _ExplodingSession:
    async def execute(self, *args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("create_batch should validate access_level before querying")

    async def flush(self):  # pragma: no cover - must not be reached
        raise AssertionError("create_batch should validate access_level before flushing")


class _EmptyScalars:
    def all(self) -> list:
        return []


class _EmptyResult:
    def scalars(self) -> _EmptyScalars:
        return _EmptyScalars()


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list = []
        self.flush_count = 0

    async def execute(self, *args, **kwargs) -> _EmptyResult:
        return _EmptyResult()

    async def delete(self, obj) -> None:
        raise AssertionError(f"did not expect existing vector chunk: {obj!r}")

    async def flush(self) -> None:
        self.flush_count += 1

    def add(self, obj) -> None:
        self.added.append(obj)


class _ScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _ScalarSession:
    def __init__(self, value) -> None:
        self.value = value

    async def execute(self, *args, **kwargs) -> _ScalarResult:
        return _ScalarResult(self.value)


@pytest.mark.asyncio
async def test_create_batch_requires_access_level_before_db_work() -> None:
    from alayaos_core.repositories.vector import VectorChunkRepository

    workspace_id = uuid.uuid4()
    repo = VectorChunkRepository(_ExplodingSession(), workspace_id)

    with pytest.raises(ValueError, match="access_level"):
        await repo.create_batch(
            [
                {
                    "workspace_id": workspace_id,
                    "source_type": "claim",
                    "source_id": uuid.uuid4(),
                    "chunk_index": 0,
                    "content": "claim text",
                    "embedding": None,
                }
            ]
        )


@pytest.mark.asyncio
async def test_create_batch_stamps_supplied_access_level() -> None:
    from alayaos_core.repositories.vector import VectorChunkRepository

    workspace_id = uuid.uuid4()
    source_id = uuid.uuid4()
    session = _RecordingSession()
    repo = VectorChunkRepository(session, workspace_id)

    created = await repo.create_batch(
        [
            {
                "workspace_id": workspace_id,
                "source_type": "entity",
                "source_id": source_id,
                "chunk_index": 0,
                "content": "entity text",
                "embedding": None,
                "access_level": "private",
            }
        ]
    )

    assert created == 1
    assert session.added[0].access_level == "private"


@pytest.mark.asyncio
async def test_get_access_level_for_claim_uses_most_restrictive_source() -> None:
    from alayaos_core.repositories.vector import VectorChunkRepository

    repo = VectorChunkRepository(_ScalarSession(3), uuid.uuid4())

    access_level = await repo.get_access_level_for_source("claim", uuid.uuid4())

    assert access_level == "restricted"


@pytest.mark.asyncio
async def test_get_access_level_for_sourceless_claim_is_restricted() -> None:
    from alayaos_core.repositories.vector import VectorChunkRepository

    repo = VectorChunkRepository(_ScalarSession(None), uuid.uuid4())

    access_level = await repo.get_access_level_for_source("claim", uuid.uuid4())

    assert access_level == "restricted"


@pytest.mark.asyncio
async def test_get_access_level_for_entity_without_sourced_claims_is_restricted() -> None:
    from alayaos_core.repositories.vector import VectorChunkRepository

    repo = VectorChunkRepository(_ScalarSession(None), uuid.uuid4())

    access_level = await repo.get_access_level_for_source("entity", uuid.uuid4())

    assert access_level == "restricted"


@pytest.mark.asyncio
async def test_get_access_level_for_event_with_unknown_level_is_restricted() -> None:
    from alayaos_core.repositories.vector import VectorChunkRepository

    repo = VectorChunkRepository(_ScalarSession("workspace-secret"), uuid.uuid4())

    access_level = await repo.get_access_level_for_source("event", uuid.uuid4())

    assert access_level == "restricted"


@pytest.mark.asyncio
async def test_get_access_level_for_unknown_source_type_is_restricted() -> None:
    from alayaos_core.repositories.vector import VectorChunkRepository

    repo = VectorChunkRepository(_ExplodingSession(), uuid.uuid4())

    access_level = await repo.get_access_level_for_source("legacy-unknown", uuid.uuid4())

    assert access_level == "restricted"
