"""Bounded applicability predicates. No Python eval, legal seeds or classification law."""
import re
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Id, Sha256, Applicability
from .device_profile import FIELDS, HIGH_IMPACT, ProfilePreview, canonical
from .regulatory_registry import digest

VERSION = "tri-state-applicability-v1"
Truth = Literal["true", "false", "unknown"]


class LegalCondition(Contract):
    requirement_id: Id
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    exact_quote: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def bounds(self):
        if self.end - self.start != len(self.exact_quote):
            raise ValueError("Invalid applicability legal quote bounds")
        return self


class Predicate(Contract):
    id: Id
    op: Literal["all", "any", "not", "always", "is_true", "is_false", "equals", "one_of"]
    field: str | None = None
    values: list[str] = Field(default_factory=list, max_length=30)
    legal_ref_ids: list[Id] = Field(default_factory=list, max_length=30)
    children: list["Predicate"] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def shape(self):
        branch = self.op in {"all", "any", "not"}
        if branch:
            if not self.children or self.field is not None or self.values or (self.op == "not" and len(self.children) != 1):
                raise ValueError("Invalid predicate composition")
        elif self.children or (self.op != "always" and self.field not in FIELDS) or not self.legal_ref_ids:
            raise ValueError("Leaf predicate requires allowed field and legal source")
        if self.op == "always" and (self.field is not None or self.values):
            raise ValueError("Unconditional predicates cannot supply device facts")
        if self.op in {"is_true", "is_false"} and self.values:
            raise ValueError("Boolean predicates have no implicit comparison values")
        if self.op in {"equals", "one_of"} and (not self.values or any(not v.strip() or len(v) > 1000 for v in self.values)):
            raise ValueError("Comparison requires literal values")
        if self.op == "equals" and len(self.values) != 1:
            raise ValueError("Equality requires one literal value")
        return self


class ApplicabilityRule(Contract):
    schema_version: Literal[1] = 1
    id: Id
    edition_id: Id
    requirement_id: Id
    legal_refs: dict[Id, LegalCondition] = Field(min_length=1, max_length=100)
    applies_when: Predicate
    except_when: list[Predicate] = Field(default_factory=list, max_length=10)
    exclusion_rationale: str | None = Field(default=None, min_length=1, max_length=2000)
    exclusion_ref_ids: list[Id] = Field(default_factory=list, max_length=30)
    candidate_category: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def bounded(self):
        ids = set()
        def walk(node, depth):
            if depth > 8 or len(ids) >= 100 or node.id in ids:
                raise ValueError("Predicate tree is overlarge or has duplicate node IDs")
            ids.add(node.id)
            if any(key not in self.legal_refs for key in node.legal_ref_ids):
                raise ValueError("Predicate refers to unknown legal condition")
            for child in node.children:
                walk(child, depth + 1)
        for node in [self.applies_when, *self.except_when]:
            walk(node, 1)
        if any(key not in self.legal_refs for key in self.exclusion_ref_ids):
            raise ValueError("Exclusion refers to unknown legal condition")
        if bool(self.exclusion_rationale) != bool(self.exclusion_ref_ids):
            raise ValueError("Exclusion rationale and legal sources are both required")
        return self

    def fields(self) -> list[str]:
        found = set()
        def walk(node):
            if node.field:
                found.add(node.field)
            for child in node.children:
                walk(child)
        for node in [self.applies_when, *self.except_when]:
            walk(node)
        return sorted(found)


class PredicateTrace(Contract):
    id: Id
    op: str
    field: str | None = None
    truth: Truth
    reason_code: str
    legal_ref_ids: list[Id]
    value: str | None = None
    expected_values: list[str] = Field(default_factory=list)


class CandidateAssessment(Contract):
    schema_version: Literal[1] = 1
    status: Applicability
    candidate_status: Literal["applicable", "not_applicable"] | None = None
    requirement_id: Id
    edition_id: Id
    rule_id: Id | None = None
    predicates: list[PredicateTrace] = Field(default_factory=list)
    legal_sources: dict[str, dict] = Field(default_factory=dict)
    device_attributes: dict[str, dict] = Field(default_factory=dict)
    reason_codes: list[str]
    questions: dict[str, str] = Field(default_factory=dict)
    exclusion_supported: bool = False
    exclusion_rationale: str | None = None
    review_required: bool = True
    classification_candidate: str | None = None
    classification_status: Literal["requires_review"] = "requires_review"
    evidence_sufficiency: Literal["not_assessed"] = "not_assessed"
    human_override: dict | None = None
    engine_version: Literal["tri-state-applicability-v1"] = VERSION

    @model_validator(mode="after")
    def exclusions(self):
        if self.status == "not_applicable" and (not self.exclusion_supported or not self.exclusion_rationale
                or not self.legal_sources or not any(a.get("evidence_ids") for a in self.device_attributes.values())):
            raise ValueError("Not applicable requires source-backed exclusion rationale")
        if self.classification_candidate and not self.review_required:
            raise ValueError("Classification candidates require specialist review")
        return self


def combine(op: str, values: list[Truth]) -> Truth:
    if op == "not":
        return {"true": "false", "false": "true", "unknown": "unknown"}[values[0]]
    if op == "all":
        return "false" if "false" in values else "unknown" if "unknown" in values else "true"
    return "true" if "true" in values else "unknown" if "unknown" in values else "false"


def attribute_context(preview: ProfilePreview, fields: list[str]) -> dict:
    attrs = {a.name: a for a in preview.profile.attributes}
    result = {}
    for field in fields:
        attr = attrs[field]
        data = attr.model_dump(mode="json")
        data["evidence"] = {key: preview.evidence[key].model_dump(mode="json") for key in attr.evidence_ids}
        result[field] = data
    return result


def _value(attribute: dict) -> tuple[str | None, str]:
    if attribute["status"] == "conflicting":
        return None, "conflicting_profile_attribute"
    value = attribute["value"]
    if value is None or not value.strip() or canonical(value) in {"unknown", "unspecified", "n/a", "requires_review", "requires review", "not provided", "not specified"}:
        return None, "missing_profile_attribute"
    if attribute["origin"] != "source" or not attribute["evidence_ids"]:
        return None, "profile_assertion_needs_document_source"
    if attribute["status"] != "user_confirmed" or attribute["review_state"] != "accepted":
        return None, "profile_attribute_needs_confirmation"
    if re.search(r"\b(?:may|might|could|possibly|shall|must)\b", value, re.I):
        return None, "conditional_or_normative_profile_wording"
    if attribute["name"] in {"intended_purpose", "target_population", "anatomical_use"} and (
            re.search(r"(?:;|\n|\bor\b|\band\b)", value, re.I)):
        return None, "multiple_purposes_or_populations_require_review"
    return value, "confirmed_source_attribute"


def _boolean(value: str, field: str) -> Truth:
    key = canonical(value)
    positive = {"yes", "true"}
    negative = {"no", "false"}
    special = {
        "sterile": ({"sterile"}, {"not sterile", "nonsterile", "non-sterile"}),
        "invasive": ({"invasive"}, {"not invasive", "non-invasive", "non invasive"}),
        "implantable": ({"implantable"}, {"not implantable", "non-implantable"}),
        "active": ({"active", "powered"}, {"passive", "not active", "unpowered"}),
        "software": ({"software"}, {"no software"}),
        "reusable": ({"reusable"}, {"single use", "single-use", "not reusable"}),
    }
    yes, no = special.get(field, (set(), set()))
    return "true" if key in positive | yes else "false" if key in negative | no else "unknown"


def decide(rule: ApplicabilityRule, preview: ProfilePreview, legal_sources: dict) -> CandidateAssessment:
    """Pure candidate reasoning; service must first verify registry/rule authority."""
    context = attribute_context(preview, rule.fields())
    traces = []
    problems = {}
    def evaluate(node):
        if node.children:
            truth = combine(node.op, [evaluate(child) for child in node.children])
            reason, value = "composed_predicate", None
        elif node.op == "always":
            truth, reason, value = "true", "explicit_reviewed_unconditional_scope", None
        else:
            value, reason = _value(context[node.field])
            truth = "unknown"
            if value is not None:
                if node.op in {"is_true", "is_false"}:
                    truth = _boolean(value, node.field)
                    if node.op == "is_false":
                        truth = combine("not", [truth])
                    if truth == "unknown":
                        reason = "unrecognized_boolean_value"
                else:
                    truth = "true" if canonical(value) in {canonical(v) for v in node.values} else "false"
                    reason = "literal_comparison"
            if truth == "unknown":
                problems[node.field] = reason
        traces.append(PredicateTrace(id=node.id, op=node.op, field=node.field, truth=truth,
            reason_code=reason, value=value, expected_values=node.values, legal_ref_ids=node.legal_ref_ids))
        return truth
    base = evaluate(rule.applies_when)
    exceptions = [evaluate(node) for node in rule.except_when]
    candidate, codes = None, []
    if "true" in exceptions:
        candidate, status = "not_applicable", "not_applicable"
        codes.append("verified_exception_matches")
    elif base == "false":
        candidate, status = "not_applicable", "not_applicable"
        codes.append("verified_scope_predicate_false")
    elif base == "true" and "unknown" not in exceptions:
        candidate, status = "applicable", "applicable"
        codes.append("verified_scope_predicates_true")
    else:
        known = any(t.field and t.truth != "unknown" for t in traces)
        status = "conditional" if known or base == "true" else "unknown"
        codes.append("unresolved_scope_or_exception")
    exclusion = bool(candidate == "not_applicable" and rule.exclusion_rationale and rule.exclusion_ref_ids
                     and any(t.field and t.truth != "unknown" for t in traces))
    if candidate == "not_applicable" and not exclusion:
        status = "requires_human_review"
        codes.append("exclusion_rationale_or_device_source_missing")
    ambiguous = {"conflicting_profile_attribute", "multiple_purposes_or_populations_require_review"}
    if ambiguous & set(problems.values()):
        status = "requires_human_review"
        codes.extend(sorted(ambiguous & set(problems.values())))
    if candidate and HIGH_IMPACT & set(context):
        status = "requires_human_review"
        codes.append("high_impact_attributes_require_specialist")
    classification_requested = bool(rule.candidate_category and candidate == "applicable")
    known_device_fact = any(t.field and t.truth != "unknown" for t in traces)
    classification = rule.candidate_category if classification_requested and known_device_fact else None
    if classification_requested:
        status = "requires_human_review"
        codes.append("classification_is_candidate_only")
        if not known_device_fact:
            codes.append("classification_needs_sourced_device_attributes")
    questions = {field: "Confirm and source " + field.replace("_", " ") +
        " for this product; resolve scope or conflicting descriptions." for field in problems}
    if classification_requested and not known_device_fact:
        questions["classification_scope"] = "Supply reviewed device-source attributes and a grounded qualification predicate before proposing a category."
    return CandidateAssessment(status=status, candidate_status=candidate,
        requirement_id=rule.requirement_id, edition_id=rule.edition_id, rule_id=rule.id,
        predicates=traces, legal_sources=legal_sources, device_attributes=context,
        reason_codes=sorted(set(codes)), questions=questions,
        exclusion_supported=exclusion, exclusion_rationale=rule.exclusion_rationale if exclusion else None,
        classification_candidate=classification)
