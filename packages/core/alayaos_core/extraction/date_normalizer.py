"""DateNormalizer: parse natural-language dates to bounded ISO 8601 values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from dateutil.relativedelta import relativedelta

SANITY_PAST_YEARS = 10
SANITY_FUTURE_YEARS = 2
FailureReason = Literal["empty_input", "unparseable_relative_date", "out_of_sanity_window"]


@dataclass(slots=True)
class NormalizedDate:
    raw: str
    iso: str | None
    anchor: datetime
    normalized: bool
    reason: FailureReason | None = None


@lru_cache(maxsize=1)
def _dateparser_module():
    import dateparser

    return dateparser


class DateNormalizer:
    """Parse Russian and English date expressions to ISO 8601."""

    def normalize(self, text: str, reference_date: datetime | None = None) -> NormalizedDate:
        anchor = reference_date or datetime.now(UTC)
        if not text or not text.strip():
            return NormalizedDate(raw=text, iso=None, anchor=anchor, normalized=False, reason="empty_input")

        parsed = _dateparser_module().parse(
            text,
            languages=["ru", "en"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": anchor,
                "RETURN_AS_TIMEZONE_AWARE": True,
            },
        )
        if parsed is None:
            return NormalizedDate(
                raw=text,
                iso=None,
                anchor=anchor,
                normalized=False,
                reason="unparseable_relative_date",
            )

        if anchor.tzinfo is not None:
            parsed = parsed.replace(tzinfo=anchor.tzinfo)

        if not _within_sanity_window(parsed, anchor):
            return NormalizedDate(raw=text, iso=None, anchor=anchor, normalized=False, reason="out_of_sanity_window")

        return NormalizedDate(raw=text, iso=parsed.isoformat(), anchor=anchor, normalized=True)


def _within_sanity_window(parsed: datetime, anchor: datetime) -> bool:
    lower = anchor - relativedelta(years=SANITY_PAST_YEARS)
    upper = anchor + relativedelta(years=SANITY_FUTURE_YEARS)
    return lower <= parsed <= upper
