"""DateNormalizer — parse natural language dates (Russian + English, relative) to ISO 8601."""

from __future__ import annotations

from datetime import UTC, datetime


class DateNormalizer:
    """Parse date strings in Russian and English (including relative dates) to ISO 8601."""

    def normalize(self, text: str, reference_date: datetime | None = None) -> str | None:
        """Parse date string and return ISO 8601 string, or None if unparseable.

        Supports Russian and English absolute and relative date expressions.
        Returns timezone-aware ISO 8601 string on success.
        """
        import dateparser

        if not text or not text.strip():
            return None

        parsed = dateparser.parse(
            text,
            languages=["ru", "en"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": reference_date or datetime.now(UTC),
                "RETURN_AS_TIMEZONE_AWARE": True,
            },
        )
        return parsed.isoformat() if parsed else None
