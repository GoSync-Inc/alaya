"""Cortex domain classification schemas."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Domain(StrEnum):
    PROJECT = "project"
    DECISION = "decision"
    STRATEGIC = "strategic"
    RISK = "risk"
    PEOPLE = "people"
    ENGINEERING = "engineering"
    KNOWLEDGE = "knowledge"
    CUSTOMER = "customer"
    SMALLTALK = "smalltalk"


class DomainScores(BaseModel):
    project: float = Field(ge=0.0, le=1.0, default=0.0)
    decision: float = Field(ge=0.0, le=1.0, default=0.0)
    strategic: float = Field(ge=0.0, le=1.0, default=0.0)
    risk: float = Field(ge=0.0, le=1.0, default=0.0)
    people: float = Field(ge=0.0, le=1.0, default=0.0)
    engineering: float = Field(ge=0.0, le=1.0, default=0.0)
    knowledge: float = Field(ge=0.0, le=1.0, default=0.0)
    customer: float = Field(ge=0.0, le=1.0, default=0.0)
    smalltalk: float = Field(ge=0.0, le=1.0, default=0.0)


class ChunkClassification(BaseModel):
    chunk_index: int
    domain_scores: DomainScores
    primary_domain: str
    is_crystal: bool
    verified: bool
    verification_changed: bool
