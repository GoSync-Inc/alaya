"""Normalization helpers for knowledge graph consolidation.

Provides transliteration and legal-suffix stripping to produce
LLM-readable hints for entity disambiguation.
"""

from __future__ import annotations

import unicodedata

from unidecode import unidecode

# Russian/CIS legal entity form abbreviations encoded as Unicode escapes.
# OOO (LLC), OAO (public JSC), ZAO (closed JSC), IP (sole trader),
# PAO (public JSC, modern form), AO (JSC, modern form).
_CYRILLIC_SUFFIXES: frozenset[str] = frozenset(
    {
        "\u041e\u041e\u041e",  # OOO
        "\u041e\u0410\u041e",  # OAO
        "\u0417\u0410\u041e",  # ZAO
        "\u0418\u041f",  # IP
        "\u041f\u0410\u041e",  # PAO
        "\u0410\u041e",  # AO
    }
)

LEGAL_SUFFIXES: frozenset[str] = frozenset(_CYRILLIC_SUFFIXES | {"LLC", "Inc", "Ltd", "GmbH"})


def strip_legal_suffixes(name: str) -> str:
    """Remove known legal form suffixes from an organization name.

    Strips tokens whose core (after removing quotation marks) appears in
    LEGAL_SUFFIXES.  Handles both Cyrillic and Latin legal forms.
    """
    # \u00ab = left guillemet, \u00bb = right guillemet
    parts = name.split()
    filtered = [p for p in parts if p.strip("\u00ab\u00bb\"'") not in LEGAL_SUFFIXES]
    return " ".join(filtered).strip()


def normalize_for_hint(name: str) -> dict[str, str]:
    """Return transliteration + legal-suffix-stripped variants as LLM hints.

    Keys returned:
    - "transliterated": unidecode of NFKC-normalised name
    - "stripped": NFKC name with legal suffixes removed
    - "stripped_transliterated": unidecode of stripped variant
    """
    nfkc = unicodedata.normalize("NFKC", name)
    transliterated = unidecode(nfkc)
    stripped = strip_legal_suffixes(nfkc)
    stripped_transliterated = unidecode(stripped)
    return {
        "transliterated": transliterated,
        "stripped": stripped,
        "stripped_transliterated": stripped_transliterated,
    }
