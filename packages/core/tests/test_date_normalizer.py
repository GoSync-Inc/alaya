"""Tests for shared DateNormalizer."""

from datetime import UTC, datetime

import pytest

from alayaos_core.extraction.date_normalizer import DateNormalizer


@pytest.mark.parametrize(
    ("text", "anchor", "expected_iso"),
    [
        ("завтра", datetime(2026, 4, 25, tzinfo=UTC), "2026-04-26T00:00:00+00:00"),
        ("1 марта", datetime(2026, 6, 1, tzinfo=UTC), "2027-03-01T00:00:00+00:00"),
        ("tomorrow", datetime(2026, 4, 25, tzinfo=UTC), "2026-04-26T00:00:00+00:00"),
    ],
)
def test_normalizes_supported_relative_and_ambiguous_dates(text: str, anchor: datetime, expected_iso: str) -> None:
    result = DateNormalizer().normalize(text, reference_date=anchor)

    assert result.normalized is True
    assert result.iso == expected_iso
    assert result.anchor == anchor
    assert result.reason is None


@pytest.mark.parametrize(
    ("text", "expected_reason"),
    [
        ("3000-01-01", "out_of_sanity_window"),
        ("", "empty_input"),
        ("fhqwhgads", "unparseable_relative_date"),
    ],
)
def test_reports_date_normalization_failures(text: str, expected_reason: str) -> None:
    result = DateNormalizer().normalize(text, reference_date=datetime(2026, 4, 25, tzinfo=UTC))

    assert result.normalized is False
    assert result.iso is None
    assert result.reason == expected_reason


def test_sanity_window_uses_calendar_year_boundary() -> None:
    anchor = datetime(2024, 2, 29, tzinfo=UTC)

    lower_boundary = DateNormalizer().normalize("2014-02-28", reference_date=anchor)
    before_boundary = DateNormalizer().normalize("2014-02-27", reference_date=anchor)
    upper_boundary = DateNormalizer().normalize("2026-02-28", reference_date=anchor)
    after_boundary = DateNormalizer().normalize("2026-03-01", reference_date=anchor)

    assert lower_boundary.normalized is True
    assert before_boundary.reason == "out_of_sanity_window"
    assert upper_boundary.normalized is True
    assert after_boundary.reason == "out_of_sanity_window"
