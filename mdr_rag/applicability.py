"""Conservative, sourced scope assessment; profile facts are never verified."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from .source_buffer import ClaimEvidenceLink


class ProfileFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: Any
    verified: Literal[False] = False


class ApplicabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["applicable", "uncertain", "possibly_not_applicable"]
    reason: str
    legal_conditions: list[str]
    legal_citations: list[ClaimEvidenceLink]
    profile_facts: list[ProfileFact]
    missing_facts: list[str]
    retrieval_policy: Literal["search_device_evidence"] = "search_device_evidence"
    method: Literal["conservative_explicit_actor_v1"] = "conservative_explicit_actor_v1"
    human_verified: Literal[False] = False


class ApplicabilityAnalyst:
    def assess(self, requirement, anchor, profile):
        facts = [ProfileFact(name=key, value=value) for key, value in sorted(profile.items())]
        actor = requirement.applies_to.strip()
        # A register paraphrase cannot establish a sourced scope condition.
        sourced = anchor is not None and actor.casefold() in anchor.exact_quote.casefold() and actor.casefold() not in {"unclear", "unspecified", ""}
        conditions = [actor] if sourced else []
        declared = profile.get("actor_role")
        tentative = sourced and isinstance(declared, str) and declared.strip() and declared.strip().casefold() != actor.casefold()
        reason = ("The cited legal actor condition differs from the explicitly unverified actor_role; applicability remains tentative."
                  if tentative else "Legal scope and unverified profile facts do not establish confirmed applicability; specialist verification is required.")
        missing = ["Verify the profile facts and device/entity scope against every legal condition and exception."]
        if not sourced:
            missing.append("A raw legal citation establishing the register's scope condition is unavailable.")
        if not declared:
            missing.append("Supply and independently confirm actor_role; absence is not evidence of non-applicability.")
        return ApplicabilityResult(status="possibly_not_applicable" if tentative else "uncertain",
            reason=reason, legal_conditions=conditions, legal_citations=[anchor] if anchor else [],
            profile_facts=facts, missing_facts=missing)
