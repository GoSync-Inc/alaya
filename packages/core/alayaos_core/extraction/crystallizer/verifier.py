"""CrystallizerVerifier — double-pass extraction verification."""

from __future__ import annotations

from alayaos_core.extraction.schemas import ExtractionResult
from alayaos_core.llm.interface import LLMServiceInterface, LLMUsage


class CrystallizerVerifier:
    def __init__(self, llm: LLMServiceInterface) -> None:
        self.llm = llm

    async def verify(
        self,
        chunk_text: str,
        system_prompt: str,
        initial_result: ExtractionResult,
    ) -> tuple[ExtractionResult, bool, LLMUsage]:
        """Double-pass verification. Same system prompt for cache hit.

        Returns (verified_result, changed, usage).
        """
        user_text = (
            f"You previously extracted:\n{initial_result.model_dump_json(indent=2)}\n\n"
            "Review the original text and correct any:\n"
            "- False entities (not actually mentioned)\n"
            "- Wrong entity types\n"
            "- Missing relations\n"
            "- Incorrect confidence scores\n\n"
            "Return the corrected extraction."
        )
        verified, usage = await self.llm.extract(user_text, system_prompt, ExtractionResult)
        changed = verified != initial_result
        return verified, changed, usage
