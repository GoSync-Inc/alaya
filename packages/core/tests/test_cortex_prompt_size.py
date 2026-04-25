"""Prompt-size regression test for the Cortex classifier.

Asserts that the assembled classifier system prompt is large enough to be
eligible for Haiku 4.5's prompt cache (4096-token minimum) with margin.
Target: len(assembled_prompt) // 4 >= 4200 (i.e. >= 16800 chars total).

This test always runs — no external dependencies required.
"""

from alayaos_core.extraction.cortex.classifier import _CLASSIFICATION_SYSTEM_PROMPT


def test_classifier_prompt_meets_cache_eligibility() -> None:
    """Assembled classifier prompt must have >= 4200 estimator tokens.

    Haiku 4.5 requires >= 4096 tokens for prompt cache eligibility.
    We target >= 4200 as a margin buffer.

    If this test fails: add more examples to
    ``packages/core/alayaos_core/extraction/cortex/prompts.py``
    until ``len(_CLASSIFICATION_SYSTEM_PROMPT) // 4 >= 4200``.
    """
    estimator_tokens = len(_CLASSIFICATION_SYSTEM_PROMPT) // 4
    assert estimator_tokens >= 4200, (
        f"Classifier system prompt is too short for Haiku 4.5 cache eligibility. "
        f"Actual estimator tokens: {estimator_tokens} (chars: {len(_CLASSIFICATION_SYSTEM_PROMPT)}). "
        f"Target: >= 4200 estimator tokens (>= 16800 chars). "
        f"Fix: add more canonical examples to "
        f"packages/core/alayaos_core/extraction/cortex/prompts.py "
        f"until len(_CLASSIFICATION_SYSTEM_PROMPT) // 4 >= 4200."
    )
