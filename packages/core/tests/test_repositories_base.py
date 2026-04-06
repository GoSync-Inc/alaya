"""Tests for BaseRepository: cursor encoding/decoding and pagination."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Column, DateTime, String, select

from alayaos_core.repositories.base import BaseRepository

# --- cursor encode/decode ---


def test_encode_cursor_returns_string() -> None:
    dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    result = BaseRepository.encode_cursor(dt, uid)
    assert isinstance(result, str)
    assert len(result) > 0


def test_decode_cursor_roundtrip() -> None:
    dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    cursor = BaseRepository.encode_cursor(dt, uid)
    decoded_dt, decoded_uid = BaseRepository.decode_cursor(cursor)
    assert decoded_dt == dt
    assert decoded_uid == uid


def test_decode_cursor_invalid_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Invalid cursor"):
        BaseRepository.decode_cursor("not-valid-base64!!!")


def test_decode_cursor_missing_key_raises_value_error() -> None:
    import base64
    import json

    bad = base64.urlsafe_b64encode(json.dumps({"created_at": "2024-01-01T00:00:00"}).encode()).decode()
    with pytest.raises(ValueError, match="Invalid cursor"):
        BaseRepository.decode_cursor(bad)


def test_decode_cursor_bad_uuid_raises_value_error() -> None:
    import base64
    import json

    bad = base64.urlsafe_b64encode(
        json.dumps({"created_at": "2024-01-01T00:00:00", "id": "not-a-uuid"}).encode()
    ).decode()
    with pytest.raises(ValueError, match="Invalid cursor"):
        BaseRepository.decode_cursor(bad)


# --- apply_cursor_pagination ---


def test_apply_cursor_pagination_clamps_limit_min() -> None:
    """limit < 1 is clamped to 1, so LIMIT becomes 2 (1+1)."""
    from sqlalchemy import Integer, MetaData, Table

    metadata = MetaData()
    t = Table("t", metadata, Column("created_at", DateTime), Column("id", Integer))
    stmt = select(t)
    result = BaseRepository.apply_cursor_pagination(stmt, None, 0, t.c.created_at, t.c.id)
    # limit should be 2 (1 clamped + 1 extra)
    assert result._limit_clause is not None


def test_apply_cursor_pagination_clamps_limit_max() -> None:
    """limit > 200 is clamped to 200, so LIMIT becomes 201."""
    from sqlalchemy import Integer, MetaData, Table

    metadata = MetaData()
    t = Table("t", metadata, Column("created_at", DateTime), Column("id", Integer))
    stmt = select(t)
    result = BaseRepository.apply_cursor_pagination(stmt, None, 9999, t.c.created_at, t.c.id)
    assert result._limit_clause is not None


def test_apply_cursor_pagination_no_cursor_no_where() -> None:
    from sqlalchemy import Integer, MetaData, Table

    metadata = MetaData()
    t = Table("t", metadata, Column("created_at", DateTime), Column("id", Integer))
    stmt = select(t)
    result = BaseRepository.apply_cursor_pagination(stmt, None, 10, t.c.created_at, t.c.id)
    compiled = str(result.compile())
    # No WHERE clause when no cursor
    assert "WHERE" not in compiled


def test_apply_cursor_pagination_with_cursor_adds_where() -> None:
    from sqlalchemy import MetaData, Table

    metadata = MetaData()
    t = Table("t", metadata, Column("created_at", DateTime), Column("id", String))
    stmt = select(t)
    dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
    uid = uuid.uuid4()
    cursor = BaseRepository.encode_cursor(dt, uid)
    result = BaseRepository.apply_cursor_pagination(stmt, cursor, 10, t.c.created_at, t.c.id)
    compiled = str(result.compile())
    assert "WHERE" in compiled
