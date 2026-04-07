"""Cortex domain classifier with double-pass verification."""

import tiktoken

from alayaos_core.extraction.cortex.chunker import RawChunk
from alayaos_core.extraction.cortex.schemas import Domain, DomainScores
from alayaos_core.llm.interface import LLMServiceInterface, LLMUsage

_CLASSIFICATION_SYSTEM_PROMPT = """\
You are a workplace communication classifier. Analyze the text and score each domain from 0.0 to 1.0 based on relevance:

- project: Project management, tasks, milestones, sprints, deadlines
- decision: Decisions made, approvals, rejections, choices
- strategic: Strategy, OKRs, goals, roadmap, vision
- risk: Risks, blockers, issues, concerns, warnings
- people: People, team changes, hiring, performance, org structure
- engineering: Technical details, code, architecture, infrastructure
- knowledge: Documentation, processes, how-tos, best practices
- customer: Customers, users, feedback, support, sales
- smalltalk: Casual chat, greetings, jokes, off-topic

Return scores for ALL domains. Multiple domains can score high simultaneously."""


def _combine_usage(u1: LLMUsage, u2: LLMUsage) -> LLMUsage:
    return LLMUsage(
        tokens_in=u1.tokens_in + u2.tokens_in,
        tokens_out=u1.tokens_out + u2.tokens_out,
        tokens_cached=u1.tokens_cached + u2.tokens_cached,
        cost_usd=u1.cost_usd + u2.cost_usd,
    )


class CortexClassifier:
    def __init__(
        self,
        llm: LLMServiceInterface,
        crystal_threshold: float = 0.1,
        truncation_tokens: int = 800,
    ) -> None:
        self.llm = llm
        self.crystal_threshold = crystal_threshold
        self.truncation_tokens = truncation_tokens
        self._encoder = tiktoken.get_encoding("cl100k_base")

    def _truncate(self, text: str) -> str:
        tokens = self._encoder.encode(text)
        if len(tokens) <= self.truncation_tokens:
            return text
        return self._encoder.decode(tokens[: self.truncation_tokens])

    async def classify(self, chunk: RawChunk) -> tuple[DomainScores, LLMUsage]:
        """Classify a chunk into domain scores."""
        truncated = self._truncate(chunk.text)
        scores, usage = await self.llm.extract(
            truncated,
            _CLASSIFICATION_SYSTEM_PROMPT,
            DomainScores,
        )
        return scores, usage

    async def verify(self, chunk: RawChunk, initial_scores: DomainScores) -> tuple[DomainScores, bool, LLMUsage]:
        """Verify and optionally correct initial classification."""
        truncated = self._truncate(chunk.text)
        user_text = (
            f"{truncated}\n\nPrevious classification: {initial_scores.model_dump_json()}. Review and correct if needed."
        )
        verified, usage = await self.llm.extract(
            user_text,
            _CLASSIFICATION_SYSTEM_PROMPT,
            DomainScores,
        )
        changed = verified != initial_scores
        return verified, changed, usage

    async def classify_and_verify(self, chunk: RawChunk) -> tuple[DomainScores, bool, LLMUsage]:
        """Classify and then verify — returns (final_scores, changed, combined_usage)."""
        initial, u1 = await self.classify(chunk)
        final, changed, u2 = await self.verify(chunk, initial)
        combined = _combine_usage(u1, u2)
        return final, changed, combined

    def is_crystal(self, scores: DomainScores) -> bool:
        """Return True if any non-SMALLTALK domain score >= crystal_threshold."""
        return any(getattr(scores, d.value, 0.0) >= self.crystal_threshold for d in Domain if d != Domain.SMALLTALK)

    def primary_domain(self, scores: DomainScores) -> str:
        """Return domain name with highest score."""
        return max(Domain, key=lambda d: getattr(scores, d.value, 0.0)).value
