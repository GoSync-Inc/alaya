"""Tests for SQLAlchemy base and timestamp mixin."""

from sqlalchemy import inspect
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base, TimestampMixin


class SampleModel(Base, TimestampMixin):
    __tablename__ = "sample_model"

    id: Mapped[int] = mapped_column(primary_key=True)


def test_base_is_declarative_base() -> None:
    """Base must be a DeclarativeBase subclass."""
    assert hasattr(Base, "metadata")
    assert hasattr(Base, "registry")


def test_timestamp_mixin_has_created_at() -> None:
    """TimestampMixin must provide created_at column."""
    mapper = inspect(SampleModel)
    column_names = [c.key for c in mapper.columns]
    assert "created_at" in column_names


def test_timestamp_mixin_has_updated_at() -> None:
    """TimestampMixin must provide updated_at column."""
    mapper = inspect(SampleModel)
    column_names = [c.key for c in mapper.columns]
    assert "updated_at" in column_names


def test_created_at_is_timezone_aware() -> None:
    """created_at column must have timezone=True."""
    mapper = inspect(SampleModel)
    col = mapper.columns["created_at"]
    assert col.type.timezone is True


def test_updated_at_is_timezone_aware() -> None:
    """updated_at column must have timezone=True."""
    mapper = inspect(SampleModel)
    col = mapper.columns["updated_at"]
    assert col.type.timezone is True


def test_timestamp_columns_not_nullable() -> None:
    """Both timestamp columns must be NOT NULL."""
    mapper = inspect(SampleModel)
    assert mapper.columns["created_at"].nullable is False
    assert mapper.columns["updated_at"].nullable is False
