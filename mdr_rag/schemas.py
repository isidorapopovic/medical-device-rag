"""Strict, limited output vocabularies for extraction and assessment."""
from typing import Literal
from pydantic import BaseModel, Field, StrictInt


class RequirementCandidate(BaseModel):
    requirement: str = Field(description="One atomic obligation expressed in own words")
    exact_quote: str = Field(description="Verbatim short consecutive quotation from supplied text")
    provision: str = Field(description="Article or Annex point if visible, otherwise 'unspecified'")
    applies_to: str = Field(description="Entity or device type addressed, if explicit, otherwise 'unclear'")


class RequirementBatch(BaseModel):
    items: list[RequirementCandidate]


class QuotedReference(BaseModel):
    source_id: str
    exact_quote: str = Field(min_length=1)
    start: StrictInt | None = Field(default=None, ge=0)
    end: StrictInt | None = Field(default=None, gt=0)
    purpose: Literal["legal_basis", "device_support", "contradiction", "applicability"] = "device_support"


class FindingClaim(BaseModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence: list[QuotedReference] = Field(default_factory=list)


class Finding(BaseModel):
    status: Literal["supported", "partial", "not_found", "needs_review", "possibly_not_applicable"]
    explanation: str
    evidence_ids: list[str]
    missing_information: list[str]
    recommended_actions: list[str]
    applicability_reason: str
    claims: list[FindingClaim] = Field(default_factory=list)


class Answer(BaseModel):
    answer: str
    source_ids: list[str]
    limitations: list[str]


class ClaimEvidence(BaseModel):
    source_id: str
    exact_quote: str = Field(min_length=12, description="Verbatim supporting quote from the cited passage")
    start: StrictInt | None = Field(default=None, ge=0)
    end: StrictInt | None = Field(default=None, gt=0)


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
