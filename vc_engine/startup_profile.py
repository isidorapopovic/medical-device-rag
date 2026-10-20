"""Editable, strictly typed startup JSON; declarations are not verification."""
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .models import clean

PROFILE_FIELDS = ("name", "device_name", "device_description", "intended_use", "clinical_indication",
                  "patient_population", "input_modality", "target_user", "workflow", "technology",
                  "jurisdiction", "claimed_regulatory_status", "funding_stage")
GAP_CATEGORIES = ("clinical_publications", "external_validation", "prospective_evidence", "comparator_studies",
                  "reimbursement_evidence", "regulatory_documentation", "intended_use_details")
GapStatus = Literal["supported_by_source", "claimed_only", "not_found_in_index", "conflicting", "needs_review"]
MatchStatus = Literal["match", "mismatch", "unknown"]


@dataclass(frozen=True)
class ProfileSource:
    source_id: str
    text: str
    source_url: str | None = None
    page: int | None = None
    chunk: str | None = None
    origin: str = "user_supplied"


@dataclass(frozen=True)
class FieldAnchor:
    field: str
    source_id: str
    quote: str


@dataclass(frozen=True)
class EvidenceClaim:
    category: str
    source_id: str
    quote: str
    stance: Literal["supports", "contradicts"] = "supports"
    reviewed_by: str | None = None
    review_note: str | None = None


@dataclass(frozen=True)
class StartupProfile:
    name: str | None = None
    device_name: str | None = None
    device_description: str | None = None
    intended_use: str | None = None
    clinical_indication: str | None = None
    patient_population: str | None = None
    input_modality: str | None = None
    target_user: str | None = None
    workflow: str | None = None
    technology: str | None = None
    jurisdiction: str | None = None
    claimed_regulatory_status: str | None = None
    funding_stage: str | None = None
    sources: tuple[ProfileSource, ...] = ()
    field_evidence: tuple[FieldAnchor, ...] = ()
    evidence_claims: tuple[EvidenceClaim, ...] = ()
    unknown_fields: tuple[str, ...] = ()
    reviewed_by: str | None = None
    reviewed_fingerprint: str | None = None
    input_sha256: str | None = None

    @property
    def fingerprint(self) -> str:
        payload = asdict(self)
        for key in ("reviewed_by", "reviewed_fingerprint", "input_sha256"):
            payload.pop(key)
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    @property
    def review_status(self) -> str:
        return "user_reviewed" if self.reviewed_by and self.reviewed_fingerprint == self.fingerprint else "pending_review"


def _string(value, label: str, *, required: bool = False) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{label} must be a string or null")
    result = clean(value)
    if required and not result:
        raise ValueError(f"{label} must not be blank")
    if result and len(result) > 20000:
        raise ValueError(f"{label} exceeds 20000 characters")
    return result


def _items(payload: dict, key: str, cls):
    items = payload.get(key, [])
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError(f"{key} must be a list of at most 100 objects")
    allowed = set(cls.__dataclass_fields__)
    result = []
    for item in items:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError(f"Invalid {key} object fields")
        normalized = dict(item)
        for name, value in item.items():
            if name == "page":
                if value is not None and (type(value) is not int or value < 1):
                    raise ValueError("Source page must be a positive integer or null")
            elif name in {"text", "quote"}:
                if not isinstance(value, str) or not value.strip() or len(value) > 100000:
                    raise ValueError(f"{key}.{name} must contain literal source text (at most 100000 characters)")
            else:
                normalized[name] = _string(value, f"{key}.{name}")
        try:
            result.append(cls(**normalized))
        except TypeError as exc:
            raise ValueError(f"Missing required {key} fields") from exc
    return tuple(result)


def profile_from_dict(payload: dict, *, reviewer: str | None = None, input_sha256: str | None = None) -> StartupProfile:
    if not isinstance(payload, dict):
        raise ValueError("Startup profile must be a JSON object")
    allowed = set(StartupProfile.__dataclass_fields__) | {"review_status", "schema_version"}
    if set(payload) - allowed:
        raise ValueError("Unknown startup profile fields: " + ", ".join(sorted(set(payload) - allowed)))
    if type(payload.get("schema_version", 1)) is not int or payload.get("schema_version", 1) != 1:
        raise ValueError("Unsupported startup profile schema")
    fields = {key: _string(payload.get(key), key) for key in PROFILE_FIELDS}
    unknown = tuple(key for key, value in fields.items() if value is None)
    supplied_unknown = payload.get("unknown_fields", [])
    if not isinstance(supplied_unknown, list) or any(key not in PROFILE_FIELDS for key in supplied_unknown):
        raise ValueError("unknown_fields must list valid profile field names")
    sources = _items(payload, "sources", ProfileSource)
    anchors = _items(payload, "field_evidence", FieldAnchor)
    claims = _items(payload, "evidence_claims", EvidenceClaim)
    source_map = {source.source_id: source for source in sources}
    if len(source_map) != len(sources) or any(not source.source_id for source in sources):
        raise ValueError("Source IDs must be nonblank and unique")
    for source in sources:
        if source.origin not in {"user_supplied", "pitch_deck", "publication", "official_document"}:
            raise ValueError("Unsupported profile source origin")
    for item in (*anchors, *claims):
        source = source_map.get(item.source_id)
        if source is None or not item.quote or item.quote not in source.text or len(item.quote) > 1000:
            raise ValueError("Every anchor/claim needs an exact short quote in its named source (at most 1000 characters)")
    for anchor in anchors:
        if anchor.field not in PROFILE_FIELDS or not fields[anchor.field]:
            raise ValueError("Field anchor must reference a populated profile field")
        if fields[anchor.field].casefold() not in clean(anchor.quote).casefold():
            raise ValueError("An anchored field must retain its literal value in the supporting quote")
    for claim in claims:
        if claim.category not in GAP_CATEGORIES or claim.stance not in {"supports", "contradicts"}:
            raise ValueError("Invalid evidence category/stance")
        if claim.reviewed_by and not claim.review_note:
            raise ValueError("Reviewed evidence claims require review_note")
    profile = StartupProfile(**fields, sources=sources, field_evidence=anchors, evidence_claims=claims,
        unknown_fields=unknown, reviewed_by=_string(payload.get("reviewed_by"), "reviewed_by"),
        reviewed_fingerprint=_string(payload.get("reviewed_fingerprint"), "reviewed_fingerprint"),
        input_sha256=input_sha256 or _string(payload.get("input_sha256"), "input_sha256"))
    if reviewer is not None:
        reviewer = _string(reviewer, "reviewer", required=True)
        from dataclasses import replace
        profile = replace(profile, reviewed_by=reviewer, reviewed_fingerprint=profile.fingerprint)
    return profile


def load_profile(path: str | Path, *, reviewer: str | None = None) -> StartupProfile:
    path = Path(path)
    if path.suffix.casefold() != ".json":
        raise ValueError("Task 03 accepts structured .json profiles; automatic deck extraction is not implemented")
    payload = path.read_bytes()
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("Startup JSON exceeds 2 MiB")
    return profile_from_dict(json.loads(payload.decode("utf-8-sig")), reviewer=reviewer,
                             input_sha256=hashlib.sha256(payload).hexdigest())


def profile_payload(profile: StartupProfile) -> dict:
    return json.loads(json.dumps({**asdict(profile), "schema_version": 1, "review_status": profile.review_status}))


@dataclass(frozen=True)
class FieldComparison:
    field: str
    status: MatchStatus
    profile_value: str | None
    candidate_value: str | None
    similarity: float
    weight: float
    reason: str
    evidence: tuple[dict, ...] = ()
    profile_evidence: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Comparable:
    source_id: str
    kind: str
    name: str
    score: float
    coverage: float
    confidence: str
    fields: tuple[FieldComparison, ...]
    evidence_status: str
    source_links: tuple[str, ...]
    regulatory: dict
    rationale: tuple[str, ...]
    uncertainty: tuple[str, ...]
    excluded: bool = False


@dataclass(frozen=True)
class ComparisonReport:
    profile_fingerprint: str
    profile_review_status: str
    results: tuple[Comparable, ...]
    excluded_candidates: tuple[Comparable, ...]
    weights: dict[str, float]
    candidate_counts: dict[str, int]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceGap:
    category: str
    status: GapStatus
    statement: str
    evidence: tuple[dict, ...]
    actions: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceGapReport:
    profile_fingerprint: str
    profile_review_status: str
    gaps: tuple[EvidenceGap, ...]
    index_scope: dict
    limitations: tuple[str, ...]
