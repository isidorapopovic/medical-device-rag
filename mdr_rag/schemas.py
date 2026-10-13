"""Strict, limited output vocabularies for extraction and assessment."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool


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
    role: Literal["legal_duty", "device_fact", "mixed", "applicability", "recommendation"] = "device_fact"
    category: Literal["assessment", "reason", "missing_information", "recommended_action", "applicability"] = "assessment"
    obligation_ids: list[str] = Field(default_factory=list)
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence: list[QuotedReference] = Field(default_factory=list)


class ObligationCoverage(BaseModel):
    obligation_id: str
    status: Literal["supported", "partial", "not_addressed", "uncertain"]
    evidence_ids: list[str] = Field(default_factory=list)
    addressed_qualifiers: list[str] = Field(default_factory=list)
    explanation: str
    verification: Literal["model_self_assessed_raw_citations_only"] = "model_self_assessed_raw_citations_only"


class Finding(BaseModel):
    status: Literal["supported", "partial", "not_found", "needs_review", "possibly_not_applicable", "insufficient_evidence"]
    explanation: str
    evidence_ids: list[str]
    missing_information: list[str]
    recommended_actions: list[str]
    applicability_reason: str
    claims: list[FindingClaim] = Field(default_factory=list)
    obligation_coverage: list[ObligationCoverage] = Field(default_factory=list)


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


class StructuredClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    role: Literal["legal_duty", "device_fact", "mixed", "applicability", "recommendation"]
    category: Literal["assessment", "reason", "missing_information", "recommended_action", "applicability"]
    obligation_ids: list[str]
    evidence: list[QuotedReference]


class StructuredFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["supported", "partial", "not_found", "needs_review", "possibly_not_applicable", "insufficient_evidence"]
    claims: list[StructuredClaim] = Field(min_length=1)
    obligation_coverage: list[ObligationCoverage]


class ClaimVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    verdict: Literal["supported", "contradicted", "insufficient"]
    reason: str = Field(min_length=1)
    evidence: list[QuotedReference]


class CoverageVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    obligation_id: str
    verdict: Literal["supported", "contradicted", "insufficient"]
    claim_ids: list[str]
    covered_qualifiers: list[str]
    reason: str = Field(min_length=1)


class FindingReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_revision: str
    context_hash: str
    claims: list[ClaimVerdict]
    coverage: list[CoverageVerdict]
    status_supported: StrictBool
    applicability_supported: StrictBool


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[StructuredClaim] = Field(min_length=1)
    source_ids: list[str]
    limitations: list[str]
