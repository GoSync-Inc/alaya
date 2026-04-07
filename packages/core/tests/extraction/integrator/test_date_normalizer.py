"""Tests for DateNormalizer."""

from datetime import UTC, datetime

import pytest

from alayaos_core.extraction.integrator.date_normalizer import DateNormalizer


@pytest.fixture
def normalizer():
    return DateNormalizer()


@pytest.fixture
def ref_date():
    return datetime(2024, 4, 15, 12, 0, 0, tzinfo=UTC)


def test_english_absolute_date(normalizer):
    result = normalizer.normalize("April 15, 2024")
    assert result is not None
    assert "2024-04-15" in result


def test_russian_date(normalizer):
    result = normalizer.normalize("15 апреля 2024")
    assert result is not None
    assert "2024-04-15" in result


def test_iso_date_passthrough(normalizer):
    result = normalizer.normalize("2024-06-01")
    assert result is not None
    assert "2024-06-01" in result


def test_english_relative_date_with_reference(normalizer, ref_date):
    # "in 2 days" from April 15, 2024 → April 17, 2024
    result = normalizer.normalize("in 2 days", reference_date=ref_date)
    assert result is not None
    assert "2024-04-17" in result


def test_russian_relative_date(normalizer, ref_date):
    # "через 2 дня" from April 15 → April 17
    result = normalizer.normalize("через 2 дня", reference_date=ref_date)
    assert result is not None
    assert "2024-04-17" in result


def test_empty_string_returns_none(normalizer):
    result = normalizer.normalize("")
    assert result is None


def test_garbage_text_returns_none(normalizer):
    result = normalizer.normalize("xyz abc not a date 12345 !!!")
    assert result is None


def test_returns_iso_8601_format(normalizer):
    result = normalizer.normalize("2024-01-31")
    assert result is not None
    # ISO 8601 with timezone info
    assert "T" in result or result.startswith("2024")
