"""Tests for CortexClassifier.is_crystal with smalltalk-aware rule."""

from unittest.mock import MagicMock

import pytest

from alayaos_core.extraction.cortex.classifier import CortexClassifier
from alayaos_core.extraction.cortex.schemas import DomainScores


@pytest.fixture
def classifier() -> CortexClassifier:
    """CortexClassifier with a fake LLM (not needed for is_crystal tests)."""
    return CortexClassifier(llm=MagicMock())


def test_is_crystal_filters_pure_smalltalk(classifier: CortexClassifier) -> None:
    """Pure smalltalk (score=1.0) should not be crystal."""
    scores = DomainScores(smalltalk=1.0)
    assert not classifier.is_crystal(scores)


def test_is_crystal_filters_smalltalk_with_weak_signal(classifier: CortexClassifier) -> None:
    """Smalltalk-dominant (0.95) with weak non-st signal (people=0.25) should not be crystal."""
    scores = DomainScores(smalltalk=0.95, people=0.25)
    assert not classifier.is_crystal(scores)


def test_is_crystal_keeps_mixed_signal(classifier: CortexClassifier) -> None:
    """Smalltalk-dominant (0.9) but strong competing signal (people=0.7) should be crystal."""
    scores = DomainScores(smalltalk=0.9, people=0.7)
    assert classifier.is_crystal(scores)


def test_is_crystal_keeps_pure_project_signal(classifier: CortexClassifier) -> None:
    """Pure non-smalltalk signal (project=0.9) should be crystal."""
    scores = DomainScores(project=0.9)
    assert classifier.is_crystal(scores)
