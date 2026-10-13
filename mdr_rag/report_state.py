"""Versioned assessment snapshots, guarded mutations and compatibility exports.

The current checkpoints describe the existing pipeline, not the later six-role
orchestration or an independent semantic audit.
"""
import json
import os
import re
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .core import digest
from .schemas import Finding
from .query_planner import QueryPlan
from .retrieval_trace import RetrievalTrace
from .evidence_gate import GateDecision
from .source_buffer import ClaimEvidenceLink, ModelCallTrace, SourceBuffer, SourcePassage


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8"))


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequirementRecord(BaseModel):
    # Preserve additional legacy/register metadata verbatim.
    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=1)
    requirement: str
    exact_quote: str
    provision: str
    applies_to: str
    legal_source_chunk_id: str
    legal_source: str
    legal_page: int = Field(ge=0)
    legal_sha256: str
    requirement_revision: int = Field(default=1, ge=1)
    human_validated: bool = False


class RetrievedPassage(StateModel):
    id: str
    text: str
    meta: dict


class Dependencies(StateModel):
    profile: str
    requirement: str
    corpus: str
    query: str
    retrieval: str
    gate: str = ""
    review: str
    validation: str


Checkpoint = Literal["pending", "applicability", "queries", "retrieval", "gate", "draft", "completed"]
CHECKPOINTS = ["pending", "applicability", "queries", "retrieval", "gate", "draft", "completed"]


class RequirementSection(StateModel):
    requirement: RequirementRecord
    requirement_hash: str
    revision: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=timestamp)
    updated_at: str = Field(default_factory=timestamp)
    finding_updated_at: str | None = None
    execution_status: Literal["pending", "running", "completed", "failed", "stale"] = "pending"
    checkpoint: Checkpoint = "pending"
    applicability: Literal["applicable", "uncertain", "possibly_not_applicable"] = "uncertain"
    applicability_reason: str = "User profile and applicability have not been independently verified."
    queries: list[str] = Field(default_factory=list)
    query_plan: dict | None = None
    retrieval_trace: dict | None = None
    evidence_gate: GateDecision | None = None
    passages: list[RetrievedPassage] = Field(default_factory=list)
    retrieved_buffer_ids: list[str] = Field(default_factory=list)
    legal_anchor: ClaimEvidenceLink | None = None
    legal_anchor_issue: str | None = None
    model_calls: list[ModelCallTrace] = Field(default_factory=list)
    draft_call_id: str | None = None
    claim_links: list[ClaimEvidenceLink] = Field(default_factory=list)
    citation_issues: list[str] = Field(default_factory=list)
    draft_finding: Finding | None = None
    finding: Finding | None = None
    finding_history: list[dict] = Field(default_factory=list)
    dependencies: Dependencies | None = None
    failure_reason: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    stale_reasons: list[str] = Field(default_factory=list)
    audit_status: Literal["not_performed", "identifier_checked_only", "legacy_unverified", "raw_spans_checked", "gate_abstained"] = "not_performed"
    human_annotations: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_checkpoint(self):
        if self.query_plan is not None:
            plan = QueryPlan.model_validate(self.query_plan)
            if [q.text for q in plan.queries] != self.queries:
                raise ValueError("Saved query plan does not match section queries")
        if self.retrieval_trace is not None:
            trace = RetrievalTrace.model_validate(self.retrieval_trace)
            if [q.query for q in trace.queries] != self.queries:
                raise ValueError("Saved retrieval provenance does not match section queries")
        if self.evidence_gate is not None and {p.id for p in self.evidence_gate.passages} != {p.id for p in self.passages}:
            raise ValueError("Gate IDs do not match saved retrieval candidates")
        if self.checkpoint == "gate" and self.evidence_gate is None:
            raise ValueError("Gate checkpoint requires saved decisions")
        if self.requirement_hash != fingerprint(self.requirement.model_dump()):
            raise ValueError("Requirement hash does not match its saved content")
        if self.checkpoint in {"queries", "retrieval", "gate", "draft", "completed"} and not self.queries:
            if self.audit_status != "legacy_unverified":
                raise ValueError("Query checkpoint requires saved queries")
        if self.checkpoint == "draft" and self.draft_finding is None:
            raise ValueError("Draft checkpoint requires draft_finding")
        if self.execution_status == "completed" and (self.checkpoint != "completed" or self.finding is None):
            raise ValueError("Completed section requires a published finding")
        if self.checkpoint == "completed" and self.finding is None:
            raise ValueError("Published checkpoint requires a finding")
        for revision in self.finding_history:
            if not {"revision", "at", "requirement", "finding", "retrieved_evidence"} <= revision.keys():
                raise ValueError("Malformed finding revision")
            if RequirementRecord.model_validate(revision["requirement"]).id != self.requirement.id:
                raise ValueError("Finding history belongs to a different requirement")
            Finding.model_validate(revision["finding"])
        return self


class StageEvent(StateModel):
    at: str = Field(default_factory=timestamp)
    requirement_id: str
    stage: str
    outcome: str


class ReportState(StateModel):
    schema_version: Literal[2] = 2
    assessment_id: str
    revision: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=timestamp)
    updated_at: str = Field(default_factory=timestamp)
    legal_scope: dict
    requirement_register_hash: str
    corpus_fingerprint: str
    indexed_manifest: dict
    device_profile: dict
    profile_fingerprint: str
    config: dict
    sections: dict[str, RequirementSection]
    source_buffer: dict[str, SourcePassage] = Field(default_factory=dict)
    events: list[StageEvent] = Field(default_factory=list)
    limitations: list[str]
    provenance: dict = Field(default_factory=dict)
    partial_run: bool = True
    status_counts: dict[str, int] = Field(default_factory=dict)
    execution_counts: dict[str, int] = Field(default_factory=dict)
    human_validated: Literal[False] = False

    @model_validator(mode="after")
    def identities(self):
        validate_assessment_id(self.assessment_id)
        if not {"source", "selected_pdf_pages", "legal_version_label"} <= self.legal_scope.keys():
            raise ValueError("Legal scope requires source, version label and selected PDF pages")
        if not self.provenance.get("legacy_source"):
            required_config = {"k", "llm_model", "embedding_model", "num_ctx", "retrieval_mode", "rerank_enabled"}
            if not required_config <= self.config.keys():
                raise ValueError("Incomplete local review configuration")
            if type(self.config["k"]) is not int or self.config["k"] < 1:
                raise ValueError("Saved k must be a positive integer")
            if type(self.config["num_ctx"]) is not int or self.config["num_ctx"] < 1:
                raise ValueError("Saved context window must be a positive integer")
        if any(key != section.requirement.id for key, section in self.sections.items()):
            raise ValueError("Section key must equal requirement ID")
        buffer = SourceBuffer(self.source_buffer)
        for section in self.sections.values():
            for key in section.retrieved_buffer_ids:
                buffer.get_passage(key)
            if section.retrieval_trace is not None:
                known = {buffer.get_passage(key).chunk_id for key in section.retrieved_buffer_ids}
                if not {c["id"] for c in section.retrieval_trace["candidates"]} <= known:
                    raise ValueError("Retrieval candidates require saved source snapshots")
            for trace in section.model_calls:
                for key in trace.retrieved_buffer_ids:
                    buffer.get_passage(key)
                for item in trace.presented:
                    buffer.validate_presented(item)
            if section.legal_anchor is not None:
                buffer.validate_link(section.legal_anchor)
            for link in section.claim_links:
                trace = next((item for item in section.model_calls if item.call_id == section.draft_call_id), None)
                if trace is None or trace.outcome != "completed":
                    raise ValueError("Claim links require a completed bound draft call")
                buffer.validate_link(link, presented=trace.presented)
            for revision in section.finding_history:
                if revision.get("legal_anchor"):
                    buffer.validate_link(revision["legal_anchor"])
                for link in revision.get("claim_links", []):
                    trace = next((item for item in section.model_calls if item.call_id == revision.get("draft_call_id")), None)
                    if trace is None:
                        raise ValueError("Historical claim links have no saved model context")
                    buffer.validate_link(link, presented=trace.presented)
        return self

    def summarize(self):
        self.execution_counts = dict(Counter(s.execution_status for s in self.sections.values()))
        current = [s for s in self.sections.values() if s.execution_status == "completed"]
        self.partial_run = len(current) != len(self.sections) or bool(self.provenance.get("unrepresented_requirement_count"))
        self.status_counts = dict(Counter(s.finding.status for s in current))


def validate_assessment_id(value: str):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ValueError("assessment_id must be 1-80 letters, digits, underscores or hyphens")


def atomic_replace(source, destination):
    """Retry brief Windows reader/antivirus locks; never bypass persistent denial."""
    for attempt in range(5):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def atomic_write(path: Path, text: str):
    """Flush a same-directory temporary file before atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".assessment-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        atomic_replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"Assessment lock conflict at {path}. Wait for the other process to finish. "
            "If it crashed, verify no assessment writer is running before manually removing this lock."
        ) from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(json.dumps({"pid": os.getpid(), "created_at": timestamp()}))
        yield
    finally:
        path.unlink()


class StateStore:
    def __init__(self, state_root: Path, assessment_id: str):
        validate_assessment_id(assessment_id)
        self.assessment_id = assessment_id
        self.directory = Path(state_root) / "assessments" / assessment_id
        self.path = self.directory / "report_state.json"
        self._locked = False

    @contextmanager
    def locked(self):
        if self._locked:
            raise RuntimeError("Nested assessment mutation is not allowed")
        with exclusive_lock(self.directory / "assessment.lock"):
            self._locked = True
            try:
                yield self
            finally:
                self._locked = False

    def load(self) -> ReportState:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            state = decode_state(data)
            if state.assessment_id != self.assessment_id:
                raise ValueError("State belongs to a different assessment")
            return state
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f"Invalid assessment state at {self.path}; it was not overwritten. "
                               "Schema/content validation failed; inspect the file locally or restore a validated revision.") from exc

    def save(self, state: ReportState, expected_revision: int) -> ReportState:
        if not self._locked:
            raise RuntimeError("State mutation requires the assessment lock")
        previous_state = self.load() if self.path.exists() else None
        current = previous_state.revision if previous_state else 0
        if current != expected_revision or state.revision != expected_revision:
            raise RuntimeError(f"Assessment revision conflict: expected {expected_revision}, found {current}. Reload and retry.")
        if state.assessment_id != self.assessment_id:
            raise ValueError("Assessment identity cannot change")
        candidate = state.model_copy(deep=True)
        candidate.revision += 1
        candidate.updated_at = timestamp()
        candidate.summarize()
        try:
            candidate = ReportState.model_validate(candidate.model_dump())
        except ValueError as exc:
            raise ValueError("Assessment content validation failed; existing state was preserved") from exc
        if previous_state is not None:
            for key, passage in previous_state.source_buffer.items():
                if candidate.source_buffer.get(key) != passage:
                    raise ValueError("Existing source snapshots cannot be replaced or removed")
        payload = candidate.model_dump_json(indent=2)
        # Preserve the last committed version before replacement. No uncommitted
        # next-revision history can block recovery after an interrupted write.
        if self.path.exists():
            previous = self.path.read_text(encoding="utf-8")
            history = self.directory / "revisions" / f"{current:08d}.json"
            if history.exists() and history.read_text(encoding="utf-8") != previous:
                raise RuntimeError(f"Revision history mismatch at {history}; preserve the files and investigate.")
            if not history.exists():
                atomic_write(history, previous)
        atomic_write(self.path, payload)
        atomic_write(self.directory / "revisions" / f"{candidate.revision:08d}.json", payload)
        return candidate


def invalidate(section: RequirementSection, dependencies: Dependencies) -> bool:
    """Keep the last published revision for history; discard only stale stage inputs."""
    old = section.dependencies
    changed = [key for key in Dependencies.model_fields
               if old is None or getattr(old, key) != getattr(dependencies, key)]
    if not changed:
        return False
    # Earliest valid checkpoint, before the affected operation.
    retain = {"profile": "pending", "requirement": "applicability",
              "query": "applicability", "corpus": "queries", "retrieval": "queries",
              "gate": "retrieval", "review": "gate", "validation": "draft"}
    earliest = min([CHECKPOINTS.index(section.checkpoint)] +
                   [CHECKPOINTS.index(retain[key]) for key in changed])
    section.checkpoint = CHECKPOINTS[earliest]
    if earliest < 2:
        section.queries = []
        section.query_plan = None
    if earliest < 3:
        section.passages = []
        section.retrieval_trace = None
        section.retrieved_buffer_ids = []
    if earliest < CHECKPOINTS.index("gate"):
        section.evidence_gate = None
    if earliest < CHECKPOINTS.index("draft"):
        section.draft_finding = None
        section.draft_call_id = None
        section.claim_links = []
        section.citation_issues = []
    if earliest == 0:
        section.applicability = "uncertain"
        section.applicability_reason = "Profile changed or not verified; applicability requires human review."
    section.execution_status = "stale"
    section.stale_reasons = list(dict.fromkeys(section.stale_reasons + changed))
    section.dependencies = dependencies
    section.failure_reason = None
    section.updated_at = timestamp()
    return True


def decode_state(data) -> ReportState:
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] not in {1, 2}:
        raise ValueError("Missing or unsupported schema_version")
    if data["schema_version"] == 1:
        # Read-only schema upgrade: archived bytes stay intact. No missing source
        # snapshots/model inputs/quotes are invented or marked newly verified.
        data = dict(data, schema_version=2)
        data["provenance"] = dict(data.get("provenance", {}), state_schema_origin=1)
    try:
        return ReportState.model_validate(data)
    except ValueError as exc:
        raise ValueError("Assessment schema/content validation failed") from exc


def compatibility_report(state: ReportState, historical: bool = False) -> dict:
    rows = []
    buffer = SourceBuffer(state.source_buffer)
    for section in state.sections.values():
        if section.finding is None or (section.execution_status != "completed" and not historical):
            continue
        # A stale finding is never relabelled as a current assessment.
        published = section.finding_history[-1] if section.finding_history else {}
        requirement = dict(published.get("requirement", section.requirement.model_dump()))
        anchor = published.get("legal_anchor")
        if anchor is not None:
            buffer.validate_link(anchor)
            requirement["exact_quote"] = anchor["exact_quote"]
        else:
            # Retain the legacy value in canonical state/provenance only. A
            # normalized or unaudited anchor must not be exported as an exact quote.
            requirement["exact_quote"] = ""
        published_finding = section.finding.model_dump()
        approved = {(link["claim_id"], link["chunk_id"], link["exact_quote"], link["start"], link["end"], link["purpose"])
                    for link in published.get("claim_links", [])}
        for claim in published_finding.get("claims", []):
            claim["evidence"] = [ref for ref in claim["evidence"]
                                 if (claim["claim_id"], ref["source_id"], ref["exact_quote"],
                                     ref["start"], ref["end"], ref["purpose"]) in approved]
        rows.append({
            "requirement": requirement,
            "finding": published_finding,
            "retrieved_evidence": section.finding_history[-1]["retrieved_evidence"]
                if section.finding_history else [
                    {"id": p.id, **p.meta, "excerpt": p.text} for p in section.passages],
            "section_revision": section.revision,
            "finding_updated_at": section.finding_updated_at,
            "execution_status": section.execution_status,
            "audit_status": section.audit_status,
            "legal_anchor": anchor,
            "legal_quote_verified": anchor is not None,
            "legal_anchor_issue": published.get("legal_anchor_issue", "legacy_raw_span_unverified" if not anchor else None),
            "query_plan": published.get("query_plan"),
            "retrieval_trace": published.get("retrieval_trace"),
            "evidence_gate": published.get("evidence_gate"),
            "rerank_citation_coverage": published.get("rerank_citation_coverage", []),
            "retrieved_buffer_ids": published.get("retrieved_buffer_ids", []),
            "draft_call_id": published.get("draft_call_id"),
            "claim_links": published.get("claim_links", []),
            "citation_issues": published.get("citation_issues", []),
        })
    scope = state.legal_scope
    return {
        "assessment_id": state.assessment_id, "state_revision": state.revision,
        "evidence_gate_mode": state.config.get("gate_mode", "not_performed_legacy"),
        "calibration_fingerprint": state.config.get("calibration") if state.config.get("gate_mode") else None,
        "generated_at_utc": state.updated_at,
        "model": state.config.get("llm_model", "unknown (legacy)"),
        "legal_version_label": scope["legal_version_label"],
        "legal_source": scope["source"], "selected_pdf_pages": scope["selected_pdf_pages"],
        "device_profile": state.device_profile,
        "total_extracted_requirements": len(state.sections) + state.provenance.get("unrepresented_requirement_count", 0),
        "assessed_requirements": len(rows), "partial_run": state.partial_run,
        "unreadable_selected_pages": scope.get("unreadable_selected_pages", []),
        "rejected_unverifiable_quotes": scope.get("rejected_unverifiable_quotes", []),
        "human_validated": False, "historical_snapshot": historical,
        "status_counts": dict(Counter(row["finding"]["status"] for row in rows)),
        "execution_counts": state.execution_counts,
        "sections": {key: {"execution_status": s.execution_status, "checkpoint": s.checkpoint,
                           "revision": s.revision, "stale_reasons": s.stale_reasons,
                           "failure_reason": s.failure_reason, "audit_status": s.audit_status,
                           "evidence_gate": s.evidence_gate.model_dump() if s.evidence_gate else None}
                     for key, s in state.sections.items()},
        "findings": rows, "limitations": state.limitations,
        "provenance": {key: value for key, value in state.provenance.items() if key != "original_report"}
            | ({"original_report_retained_in_canonical_state": True} if "original_report" in state.provenance else {}),
        "source_buffer": {key: passage.model_dump() for key, passage in state.source_buffer.items()},
        "model_calls": [trace.model_dump() for section in state.sections.values() for trace in section.model_calls],
    }


def export_report(state: ReportState, destination: Path, historical: bool = False):
    from .Q_Mix_report_writer import write_markdown

    report = compatibility_report(state, historical)
    # One lock covers the JSON/Markdown export pair, including shared latest exports.
    with exclusive_lock(Path(destination) / "export.lock"):
        fd, name = tempfile.mkstemp(suffix=".md", dir=destination)
        os.close(fd)
        temporary = Path(name)
        try:
            write_markdown(report, temporary)
            atomic_write(Path(destination) / "assessment.json", json.dumps(report, indent=2, ensure_ascii=False))
            atomic_replace(temporary, Path(destination) / "assessment.md")
        finally:
            temporary.unlink(missing_ok=True)
    return report


def import_legacy(source: Path, state_root: Path, assessment_id: str) -> ReportState:
    """Explicit migration; source bytes and all original findings remain unmodified."""
    raw = Path(source).read_bytes()
    report = json.loads(raw.decode("utf-8"))
    sections = {}
    for row in report["findings"]:
        req_data = dict(row["requirement"])
        # New exports may have suppressed an unverified legacy quotation. The
        # original raw register value is not reconstructed from an empty field.
        req = RequirementRecord.model_validate(req_data)
        if req.id in sections:
            raise ValueError(f"Duplicate legacy requirement ID: {req.id}")
        finding = Finding.model_validate(row["finding"])
        evidence = [RetrievedPassage(id=p["id"], text=p.get("excerpt", ""),
                    meta={key: value for key, value in p.items() if key not in {"id", "excerpt"}})
                    for p in row.get("retrieved_evidence", [])]
        sections[req.id] = RequirementSection(
            requirement=req, requirement_hash=fingerprint(req.model_dump()),
            revision=1, execution_status="completed", checkpoint="completed",
            created_at=report["generated_at_utc"], updated_at=report["generated_at_utc"],
            finding_updated_at=report["generated_at_utc"], finding=finding,
            passages=evidence, audit_status="legacy_unverified",
            finding_history=[{"revision": 1, "at": report["generated_at_utc"],
                              "requirement": req.model_dump(), "finding": finding.model_dump(),
                              "retrieved_evidence": row.get("retrieved_evidence", [])}],
        )
    state = ReportState(
        assessment_id=assessment_id, legal_scope={
            "source": report["legal_source"], "legal_version_label": report["legal_version_label"],
            "selected_pdf_pages": report["selected_pdf_pages"],
            "unreadable_selected_pages": report.get("unreadable_selected_pages", []),
            "rejected_unverifiable_quotes": report.get("rejected_unverifiable_quotes", []),
        }, requirement_register_hash=fingerprint([s.requirement.model_dump() for s in sections.values()]),
        corpus_fingerprint="unknown-legacy", indexed_manifest={},
        device_profile=report.get("device_profile", {}),
        profile_fingerprint=fingerprint(report.get("device_profile", {})),
        config={"llm_model": report.get("model", "unknown-legacy")}, sections=sections,
        limitations=list(report.get("limitations", [])) + [
            "Imported legacy report: dependency fingerprints and independent semantic/raw-span audits are unavailable.",
            "Legacy findings retain their original status; they have not been newly verified."],
        provenance={"legacy_source": str(source), "legacy_sha256": digest(raw),
                    "original_report": report, "unrepresented_requirement_count":
                    max(0, report.get("total_extracted_requirements", len(sections)) - len(sections))},
    )
    store = StateStore(state_root, assessment_id)
    with store.locked():
        if store.path.exists():
            raise RuntimeError("Assessment already exists; import into a new assessment ID")
        state = store.save(state, expected_revision=0)
    return state
