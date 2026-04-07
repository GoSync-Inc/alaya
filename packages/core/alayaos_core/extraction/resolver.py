"""Entity resolution: normalize, match, and create entities from extraction output."""

import unicodedata


def normalize_name(name: str) -> str:
    """NFKC + lowercase + strip + zero-width removal."""
    name = unicodedata.normalize("NFKC", name)
    name = name.strip().lower()
    # Remove zero-width characters (Unicode category Cf = format characters)
    name = "".join(c for c in name if not unicodedata.category(c).startswith("Cf"))
    return name
