"""Tests for normalization.py — transliteration and legal-suffix stripping.

Cyrillic strings are defined as Unicode escapes to avoid RUF001/RUF002/RUF003.
"""

from __future__ import annotations

# Cyrillic test constants (Unicode escapes to satisfy ruff RUF001 rule)
# Meanings: OOO = Russian LLC, TIKETSKLAUD = "Tiketsklaud" (a company name)
_OOO = "\u041e\u041e\u041e"
_TIKETSKLAUD = "\u0422\u0438\u043a\u0435\u0442\u0441\u043a\u043b\u0430\u0443\u0434"
_OOO_TIKETSKLAUD = f"{_OOO} {_TIKETSKLAUD}"
_OOO_QUOTED = f"{_OOO} \u00ab{_TIKETSKLAUD}\u00bb"
_QUOTED_TIKETSKLAUD = f"\u00ab{_TIKETSKLAUD}\u00bb"


class TestStripLegalSuffixes:
    def test_strip_legal_suffixes_simple(self):
        """'OOO Tiketsklaud' -> 'Tiketsklaud' (strips Cyrillic LLC abbreviation)."""
        from alayaos_core.extraction.integrator.normalization import strip_legal_suffixes

        result = strip_legal_suffixes(_OOO_TIKETSKLAUD)
        assert result == _TIKETSKLAUD

    def test_strip_legal_suffixes_multiple(self):
        """Strips OOO leaving only the name part."""
        from alayaos_core.extraction.integrator.normalization import strip_legal_suffixes

        result = strip_legal_suffixes(_OOO_TIKETSKLAUD)
        assert _OOO not in result
        assert _TIKETSKLAUD in result

    def test_strip_legal_suffixes_quoted(self):
        """Strips OOO from 'OOO [guillemet]Tiketsklaud[/guillemet]'."""
        from alayaos_core.extraction.integrator.normalization import strip_legal_suffixes

        result = strip_legal_suffixes(_OOO_QUOTED)
        assert _OOO not in result
        assert _TIKETSKLAUD in result

    def test_strip_legal_suffixes_latin(self):
        """'Acme LLC' -> 'Acme'"""
        from alayaos_core.extraction.integrator.normalization import strip_legal_suffixes

        result = strip_legal_suffixes("Acme LLC")
        assert result == "Acme"

    def test_strip_legal_suffixes_no_suffix(self):
        """Name without legal suffix is returned unchanged."""
        from alayaos_core.extraction.integrator.normalization import strip_legal_suffixes

        result = strip_legal_suffixes(_TIKETSKLAUD)
        assert result == _TIKETSKLAUD

    def test_strip_legal_suffixes_inc(self):
        """'Apple Inc' -> 'Apple'"""
        from alayaos_core.extraction.integrator.normalization import strip_legal_suffixes

        result = strip_legal_suffixes("Apple Inc")
        assert result == "Apple"

    def test_strip_legal_suffixes_inc_with_dot(self):
        """'Apple Inc.' -> 'Apple' (trailing dot stripped before suffix matching)."""
        from alayaos_core.extraction.integrator.normalization import strip_legal_suffixes

        result = strip_legal_suffixes("Apple Inc.")
        assert result == "Apple"

    def test_strip_legal_suffixes_ltd_with_dot(self):
        """'Acme Ltd.' -> 'Acme'"""
        from alayaos_core.extraction.integrator.normalization import strip_legal_suffixes

        result = strip_legal_suffixes("Acme Ltd.")
        assert result == "Acme"


class TestNormalizeForHint:
    def test_normalize_for_hint_cyrillic(self):
        """Tiketsklaud (Cyrillic) -> transliterated 'Tiketsklaud'."""
        from alayaos_core.extraction.integrator.normalization import normalize_for_hint

        result = normalize_for_hint(_TIKETSKLAUD)
        assert result["transliterated"] == "Tiketsklaud"

    def test_normalize_for_hint_full(self):
        """All keys populated with non-empty strings; stripped excludes OOO."""
        from alayaos_core.extraction.integrator.normalization import normalize_for_hint

        result = normalize_for_hint(_OOO_QUOTED)
        assert "transliterated" in result
        assert "stripped" in result
        assert "stripped_transliterated" in result
        for key, value in result.items():
            assert isinstance(value, str), f"{key} should be a string"
        assert _OOO not in result["stripped"]
        assert len(result["transliterated"]) > 0

    def test_normalize_for_hint_returns_dict(self):
        """normalize_for_hint always returns a dict with the required keys."""
        from alayaos_core.extraction.integrator.normalization import normalize_for_hint

        result = normalize_for_hint("Some Company Ltd")
        assert isinstance(result, dict)
        required_keys = {"transliterated", "stripped", "stripped_transliterated"}
        assert required_keys.issubset(result.keys())

    def test_normalize_for_hint_latin_company(self):
        """'Google Inc' -> stripped is 'Google', stripped_transliterated is 'Google'."""
        from alayaos_core.extraction.integrator.normalization import normalize_for_hint

        result = normalize_for_hint("Google Inc")
        assert result["stripped"] == "Google"
        assert result["stripped_transliterated"] == "Google"
