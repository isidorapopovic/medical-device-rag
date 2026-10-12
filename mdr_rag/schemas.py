"""Strict, limited output vocabularies for extraction and assessment."""
from typing import Literal
from pydantic import BaseModel, Field


class RequirementCandidate(BaseModel):
    requirement: str = Field(description="One atomic obligation expressed in own words")
    exact_quote: str = Field(description="Verbatim short consecutive quotation from supplied text")
    provision: str = Field(description="Article or Annex point if visible, otherwise 'unspecified'")
    applies_to: str = Field(description="Entity or device type addressed, if explicit, otherwise 'unclear'")


class RequirementBatch(BaseModel):
    items: list[RequirementCandidate]


class Finding(BaseModel):
    status: Literal["supported", "partial", "not_found", "needs_review", "possibly_not_applicable"]
    explanation: str
    evidence_ids: list[str]
    missing_information: list[str]
    recommended_actions: list[str]
    applicability_reason: str


class Answer(BaseModel):
    answer: str
    source_ids: list[str]
    limitations: list[str]


class ClaimEvidence(BaseModel):
    source_id: str
    exact_quote: str = Field(min_length=12, description="Verbatim supporting quote from the cited passage")


class AnswerClaim(BaseModel):
    claim: str = Field(min_length=1, description="One independently checkable factual claim")
    supported: bool
    evidence: list[ClaimEvidence]


class AnswerSupportVerification(BaseModel):
    claims: list[AnswerClaim]


class RerankScore(BaseModel):
    source_id: str
    score: int = Field(ge=0, le=100)


class RerankBatch(BaseModel):
    scores: list[RerankScore]
