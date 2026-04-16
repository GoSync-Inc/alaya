"""Tests for crystallizer prompt v2 — hierarchy, date, bilingual, examples."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from alayaos_core.extraction.crystallizer.extractor import CrystallizerExtractor

# ─── Helpers ──────────────────────────────────────────────────────────────────


def make_chunk(primary_domain: str = "project", domain_scores: dict | None = None) -> MagicMock:
    chunk = MagicMock()
    chunk.primary_domain = primary_domain
    chunk.domain_scores = domain_scores or {"project": 0.8}
    return chunk


def build_prompt(
    entity_types: list[dict] | None = None,
    predicates: list[dict] | None = None,
    snapshot: list[dict] | None = None,
) -> str:
    extractor = CrystallizerExtractor(llm=MagicMock(), entity_cache=MagicMock())
    chunk = make_chunk()
    return extractor._build_prompt(
        entity_types=entity_types or [],
        predicates=predicates or [],
        snapshot=snapshot or [],
        chunk=chunk,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_prompt_contains_hierarchy_vocabulary() -> None:
    """Prompt must mention the tiered entity vocabulary with task/goal/north_star."""
    prompt = build_prompt()
    assert "task (tier 1)" in prompt
    assert "goal (tier 3)" in prompt
    assert "north_star (tier 4)" in prompt


def test_prompt_contains_current_date() -> None:
    """Prompt must contain today's date in ISO format."""
    prompt = build_prompt()
    today = date.today().isoformat()
    assert today in prompt


def test_prompt_contains_bilingual_instruction() -> None:
    """Prompt must mention Russian and English language handling."""
    prompt = build_prompt()
    # Check for bilingual instruction — must mention Russian/English extraction guidance
    assert "Russian" in prompt or "Russian" in prompt
    assert "English" in prompt
    # Must say to keep original language (not translate)
    prompt_lower = prompt.lower()
    assert "original" in prompt_lower


def test_prompt_contains_type_discrimination_examples() -> None:
    """Prompt must contain the MTS (cyrillic) example for type discrimination."""
    prompt = build_prompt()
    assert "\u041c\u0422\u0421" in prompt  # MTS in Cyrillic — intentional prompt content


def test_prompt_contains_name_length_guidance() -> None:
    """Prompt must mention 50-character limit (or similar) for entity names."""
    prompt = build_prompt()
    assert "50" in prompt


def test_prompt_contains_part_of_predicate() -> None:
    """Prompt must mention 'part_of' when predicates are listed."""
    predicates = [
        {"name": "owner", "slug": "owner"},
        {"name": "deadline", "slug": "deadline"},
    ]
    prompt = build_prompt(predicates=predicates)
    assert "part_of" in prompt
