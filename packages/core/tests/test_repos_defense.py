"""Unit tests for BaseRepository workspace_id defense-in-depth."""

import uuid
from unittest.mock import AsyncMock

import pytest

from alayaos_core.repositories.base import BaseRepository


def test_ws_filter_returns_condition_when_workspace_id_set() -> None:
    session = AsyncMock()
    ws_id = uuid.uuid4()
    repo = BaseRepository(session, workspace_id=ws_id)

    from alayaos_core.models.entity import L1Entity

    condition = repo._ws_filter(L1Entity)
    # Should not be True (the no-op)
    assert condition is not True


def test_ws_filter_returns_true_when_workspace_id_none() -> None:
    session = AsyncMock()
    repo = BaseRepository(session, workspace_id=None)

    from alayaos_core.models.entity import L1Entity

    condition = repo._ws_filter(L1Entity)
    assert condition is True
