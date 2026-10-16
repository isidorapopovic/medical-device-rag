"""New provenance contracts; legacy schemas/serialized assessments remain unchanged."""
import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .errors import CitationError

Id = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\w.-]+$")]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=1_000_000)]
Applicability = Literal["applicable", "not_applicable", "conditional", "unknown", "requires_human_review"]
EvidenceStatus = Literal["supported", "partially_supported", "contradictory", "not_found", "unverifiable"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @field_validator("*", mode="before")
    @classmethod
    def unicode_text(cls, value: Any, info) -> Any:
        if info.field_name in {"created_at", "verified_at", "finished_at"} and value is not None:
            if not isinstance(value, (str, datetime)):
                raise ValueError("Timestamp must be an ISO string or UTC datetime")
        if isinstance(value, str):
            if len(value) > 1_000_000 or any(0xD800 <= ord(c) <= 0xDFFF or c == "\x00" for c in value):
                raise ValueError("Invalid Unicode or oversized text")
            return unicodedata.normalize("NFC", value)
        if isinstance(value, (dict, list)):
            items = value.values() if isinstance(value, dict) else value
            # Nested structures are bounded and validated by their field types;
            # never allow malformed strings to bypass the Unicode boundary.
            for item in items:
                if isinstance(item, str) and any(0xD800 <= ord(c) <= 0xDFFF or c == "\x00" for c in item):
                    raise ValueError("Invalid nested Unicode")
        return value

    @field_validator("*", mode="after")
    @classmethod
    def utc_dates(cls, value: Any) -> Any:
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("Timestamp must have an explicit UTC offset")
        return value


class Document(Contract):
    id: UUID
    project_id: Id
    collection: Literal["legal", "device"]
    original_name: Annotated[str, Field(min_length=1, max_length=255)]
    mime: Annotated[str, Field(min_length=1, max_length=128)]
    sha256: Sha256
    byte_size: StrictInt = Field(ge=0)
    created_at: datetime
    version: StrictInt = Field(ge=1)
    upload_status: Literal["pending", "accepted", "rejected"] = "pending"

    @field_validator("original_name")
    @classmethod
    def basename(cls, value: str) -> str:
        if value in {".", ".."} or re.search(r"[\\/:\x00-\x1f]", value):
            raise ValueError("Original name must be a basename")
        return value


class SourceSpan(Contract):
    id: Id
    document_id: UUID
    document_version: StrictInt = Field(ge=1)
    text_hash: Sha256
    extraction_engine: Id
    extraction_version: Id
    section_path: list[Id] = Field(default_factory=list)
    physical_page_1based: StrictInt | None = Field(default=None, ge=1)
    block_index: StrictInt | None = Field(default=None, ge=0)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    text: Text
    quality_flags: list[Id] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounds(self):
        if self.end - self.start != len(self.text):
            raise ValueError("Span length differs from literal text")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.text_hash:
            raise ValueError("Span text hash mismatch")
        return self


class Citation(Contract):
    source_span_id: Id
    document_id: UUID
    document_version: StrictInt = Field(ge=1)
    original_name: Annotated[str, Field(min_length=1, max_length=255)]
    physical_page_1based: StrictInt | None = Field(default=None, ge=1)
    exact_quote: Text

    def verify(self, span: SourceSpan, document: Document, extracted_block: str | None = None) -> None:
        if (self.source_span_id != span.id or self.document_id != span.document_id
                or self.document_id != document.id or self.document_version != span.document_version
                or self.document_version != document.version or self.original_name != document.original_name
                or self.physical_page_1based != span.physical_page_1based
                or self.exact_quote != span.text
                or (extracted_block is not None and extracted_block[span.start:span.end] != span.text)):
            raise CitationError()


class RegulationEdition(Contract):
    id: Id
    regulation_id: Id
    jurisdiction: Id
    source_url: Annotated[str, Field(pattern=r"^https://", max_length=2048)]
    edition_label: Annotated[str, Field(min_length=1, max_length=255)]
    sha256: Sha256
    published: date | None = None
    amended: date | None = None
    cutoff: date | None = None
    currentness_status: Literal["unverified", "verified_as_of_date"] = "unverified"
    verified_by: Id | None = None
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def verification(self):
        if self.currentness_status == "verified_as_of_date" and (not self.verified_by or not self.verified_at):
            raise ValueError("Verified edition requires reviewer and UTC verification timestamp")
        return self


class Requirement(Contract):
    id: Id
    edition_id: Id
    legal_span_ids: list[Id] = Field(min_length=1)
    verbatim_clause: Text
    applicability_rules: list[Text] = Field(default_factory=list)
    effective_date: date | None = None
    verification: Literal["unverified", "verified", "rejected"] = "unverified"
    verified_by: Id | None = None
    verified_at: datetime | None = None
    reviewer_notes: Annotated[str, Field(max_length=10000)] = ""

    @model_validator(mode="after")
    def verified(self):
        if len(self.legal_span_ids) != len(set(self.legal_span_ids)):
            raise ValueError("Duplicate legal source IDs")
        if self.verification == "verified" and (not self.verified_by or not self.verified_at):
            raise ValueError("Verified requirement requires a reviewer and timestamp")
        return self


class DeviceAttribute(Contract):
    name: Id
    value: Annotated[str, Field(max_length=10000)] | None = None
    source_span_ids: list[Id] = Field(default_factory=list)
    status: Literal["extracted", "user_confirmed", "unknown", "conflicting"] = "unknown"

    @model_validator(mode="after")
    def grounded(self):
        if self.status == "extracted" and (self.value is None or not self.source_span_ids):
            raise ValueError("Extracted attributes require a value and source")
        return self


class DeviceProfile(Contract):
    project_id: Id
    attributes: list[DeviceAttribute] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique(self):
        if len({a.name for a in self.attributes}) != len(self.attributes):
            raise ValueError("Duplicate profile attribute")
        return self


class Finding(Contract):
    id: Id
    requirement_id: Id
    edition_id: Id
    applicability: Applicability = "unknown"
    evidence_status: EvidenceStatus = "unverifiable"
    verification: Literal["verified", "needs_review", "rejected"] = "needs_review"
    legal_citations: list[Citation] = Field(default_factory=list)
    device_citations: list[Citation] = Field(default_factory=list)
    rationale: Text
    missing_items: list[Text] = Field(default_factory=list)
    next_actions: list[Text] = Field(default_factory=list)
    reviewer_decision: Literal["pending", "accepted", "overridden", "rejected"] = "pending"
    workflow_version: Id
    model_version: Id
    config_version: Sha256

    @model_validator(mode="after")
    def evidence_required(self):
        if self.evidence_status in {"supported", "partially_supported", "contradictory"} and (
                not self.legal_citations or not self.device_citations):
            raise ValueError("Substantive evidence states require legal and device citations")
        if self.verification == "verified" and self.reviewer_decision != "accepted":
            raise ValueError("Verified findings require human acceptance")
        return self


class Usage(Contract):
    calls: StrictInt = Field(default=0, ge=0)
    input_tokens: StrictInt = Field(default=0, ge=0)
    output_tokens: StrictInt = Field(default=0, ge=0)
    estimated: bool = True
    usd: float = Field(default=0, ge=0, allow_inf_nan=False)


class AssessmentRun(Contract):
    id: UUID
    project_id: Id
    document_versions: dict[UUID, Annotated[int, Field(strict=True, ge=1)]] = Field(default_factory=dict)
    registry_revision: Id | None = None
    prompt_hashes: list[Sha256] = Field(default_factory=list)
    model_id: Annotated[str, Field(min_length=1, max_length=200)]
    embedding_id: Annotated[str, Field(min_length=1, max_length=200)]
    config_hash: Sha256
    created_at: datetime
    finished_at: datetime | None = None
    elapsed_ms: StrictInt = Field(default=0, ge=0)
    usage: Usage = Field(default_factory=Usage)
    status: Literal["draft", "blocked", "completed_with_gaps", "reviewed"] = "draft"
    errors: list[Id] = Field(default_factory=list)

    @model_validator(mode="after")
    def chronology(self):
        if self.finished_at is not None and self.finished_at < self.created_at:
            raise ValueError("Run finish precedes creation")
        return self


def validate_references(documents: list[Document], spans: list[SourceSpan], requirements: list[Requirement],
                        findings: list[Finding], *, project_id: str) -> None:
    """Validate project/version/role links, never infer legal relevance from a valid link."""
    for values in (documents, spans, requirements, findings):
        if len({item.id for item in values}) != len(values):
            raise CitationError()
    docs, sources, rules = ({item.id: item for item in values} for values in (documents, spans, requirements))
    for doc in documents:
        if doc.project_id != project_id:
            raise CitationError()
    for span in spans:
        doc = docs.get(span.document_id)
        if doc is None or doc.version != span.document_version:
            raise CitationError()
    for rule in requirements:
        if any(key not in sources or docs[sources[key].document_id].collection != "legal" for key in rule.legal_span_ids):
            raise CitationError()
    for finding in findings:
        rule = rules.get(finding.requirement_id)
        if rule is None or rule.edition_id != finding.edition_id:
            raise CitationError()
        for kind, citations in (("legal", finding.legal_citations), ("device", finding.device_citations)):
            for citation in citations:
                span = sources.get(citation.source_span_id)
                if (span is None or docs[span.document_id].collection != kind
                        or (kind == "legal" and span.id not in rule.legal_span_ids)):
                    raise CitationError()
                citation.verify(span, docs[span.document_id])


def legacy_profile(profile: dict, project_id: str) -> DeviceProfile:
    """Legacy user-supplied facts have no verified source, so stay unknown."""
    return DeviceProfile(project_id=project_id, attributes=[
        DeviceAttribute(name=key, value=str(value), status="unknown") for key, value in sorted(profile.items())])


def legacy_finding(value: dict):
    """Validate/re-emit legacy serialization without claiming new verified references."""
    from .schemas import Finding as LegacyFinding
    return LegacyFinding.model_validate(value)
