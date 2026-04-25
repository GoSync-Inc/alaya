"""Optional Anthropic count_tokens test for the Cortex classifier prompt.

Skipped unless ANTHROPIC_API_KEY is set in the environment.
When the key is present, verifies the actual Anthropic token count for the
assembled classifier system prompt is >= 4200.
"""

import os

import pytest

from alayaos_core.config import Settings
from alayaos_core.extraction.cortex.classifier import _CLASSIFICATION_SYSTEM_PROMPT


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping Anthropic count_tokens check",
)
def test_classifier_prompt_anthropic_token_count() -> None:
    """Actual Anthropic token count of the classifier prompt must be >= 4200."""
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.count_tokens(
        model=Settings().CORTEX_CLASSIFIER_MODEL,
        system=_CLASSIFICATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "hello"}],
    )
    token_count = response.input_tokens
    assert token_count >= 4200, (
        f"Anthropic token count for classifier prompt is {token_count}, "
        f"below the 4200 cache-eligibility target. "
        f"Add more canonical examples to "
        f"packages/core/alayaos_core/extraction/cortex/prompts.py."
    )
