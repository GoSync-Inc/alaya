"""Schemas for the Crystallizer pipeline stage."""

from pydantic import BaseModel

from alayaos_core.extraction.schemas import ExtractionResult
from alayaos_core.llm.interface import LLMUsage


class CrystallizerResult(BaseModel):
    extraction: ExtractionResult
    verified: bool
    verification_changed: bool
    usage_extract: LLMUsage
    usage_verify: LLMUsage


class VerificationResult(BaseModel):
    result: ExtractionResult
    changed: bool
    usage: LLMUsage
