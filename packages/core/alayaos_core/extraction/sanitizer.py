"""Input sanitizer — Security Layer 1, applied before LLM call."""

import re
import unicodedata

import structlog

log = structlog.get_logger()

# Zero-width characters to strip
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2028-\u202f\ufeff]")

# Injection patterns (log warning, do not block)
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"(forget|disregard)\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"<\s*/?\s*instructions?\s*>", re.IGNORECASE),
]

# HTML comment pattern (including multiline)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def sanitize(text: str, *, max_chars: int = 10_000) -> str:
    """Sanitize input text before LLM extraction.

    1. Unicode NFKC normalization
    2. Strip zero-width characters
    3. Strip HTML comments
    4. Cap input length
    5. Detect injection patterns (log but proceed)
    """
    # 1. Unicode NFKC
    text = unicodedata.normalize("NFKC", text)

    # 2. Zero-width
    text = _ZERO_WIDTH.sub("", text)

    # 3. HTML comments
    text = _HTML_COMMENT.sub("", text)

    # 4. Cap length
    if len(text) > max_chars:
        text = text[:max_chars]

    # 5. Injection detection (log, don't block)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            log.warning(
                "injection_pattern_detected",
                pattern=pattern.pattern,
                text_preview=text[:100],
            )

    return text
