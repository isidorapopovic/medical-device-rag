"""Versioned assessment snapshots, guarded mutations and compatibility exports.

The current checkpoints describe the existing pipeline, not the later six-role
orchestration or a semantic/citation audit that has not been implemented yet.
"""
import json
import os
import re
import tempfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .core import digest
from .schemas import Finding


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
    review: str
    validation: str


Checkpoint = Literal["pending", "applicability", "queries", "retrieval", "draft", "completed"]
CHECKPOINTS = ["pending", "applicability", "queries", "retrieval", "draft", "completed"]


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
    passages: list[RetrievedPassage] = Field(default_factory=list)
    draft_finding: Finding | None = None
    finding: Finding | None = None
    finding_history: list[dict] = Field(default_factory=list)
    dependencies: Dependencies | None = None
    failure_reason: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    stale_reasons: list[str] = Field(default_factory=list)
    audit_status: Literal["not_performed", "identifier_checked_only", "legacy_unverified"] = "not_performed"
    human_annotations: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_checkpoint(self):
        if self.requirement_hash != fingerprint(self.requirement.model_dump()):
            raise ValueError("Requirement hash does not match its saved content")
        if self.checkpoint in {"queries", "retrieval", "draft", "completed"} and not self.queries:
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
    schema_version: Literal[1] = 1
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
        return self

    def summarize(self):
        self.execution_counts = dict(Counter(s.execution_status for s in self.sections.values()))
        current = [s for s in self.sections.values() if s.execution_status == "completed"]
        self.partial_run = len(current) != len(self.sections) or bool(self.provenance.get("unrepresented_requirement_count"))
        self.status_counts = dict(Counter(s.finding.status for s in current))


def validate_assessment_id(value: str):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ValueError("assessment_id must be 1-80 letters, digits, underscores or hyphens")


def atomic_write(path: Path, text: str):
    """Flush a same-directory temporary file before atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".assessment-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
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
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise ValueError("Missing or unsupported schema_version; explicit migration is required")
            state = ReportState.model_validate(data)
            if state.assessment_id != self.assessment_id:
                raise ValueError("State belongs to a different assessment")
            return state
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f"Invalid assessment state at {self.path}; it was not overwritten. "
                               "Schema/content validation failed; inspect the file locally or restore a validated revision.") from exc

    def save(self, state: ReportState, expected_revision: int) -> ReportState:
        if not self._locked:
            raise RuntimeError("State mutation requires the assessment lock")
        current = self.load().revision if self.path.exists() else 0
        if current != expected_revision or state.revision != expected_revision:
            raise RuntimeError(f"Assessment revision conflict: expected {expected_revision}, found {current}. Reload and retry.")
        if state.assessment_id != self.assessment_id:
            raise ValueError("Assessment identity cannot change")
        candidate = state.model_copy(deep=True)
        candidate.revision += 1
        candidate.updated_at = timestamp()
        candidate.summarize()
        candidate = ReportState.model_validate(candidate.model_dump())
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
              "review": "retrieval", "validation": "draft"}
    earliest = min([CHECKPOINTS.index(section.checkpoint)] +
                   [CHECKPOINTS.index(retain[key]) for key in changed])
    section.checkpoint = CHECKPOINTS[earliest]
    if earliest < 2:
        section.queries = []
    if earliest < 3:
        section.passages = []
    if earliest < 4:
        section.draft_finding = None
    if earliest == 0:
        section.applicability = "uncertain"
        section.applicability_reason = "Profile changed or not verified; applicability requires human review."
    section.execution_status = "stale"
    section.stale_reasons = list(dict.fromkeys(section.stale_reasons + changed))
    section.dependencies = dependencies
    section.failure_reason = None
    section.updated_at = timestamp()
    return True


def compatibility_report(state: ReportState, historical: bool = False) -> dict:
    rows = []
    for section in state.sections.values():
        if section.finding is None or (section.execution_status != "completed" and not historical):
            continue
        # A stale finding is never relabelled as a current assessment.
        rows.append({
            "requirement": section.finding_history[-1]["requirement"] if section.finding_history else section.requirement.model_dump(),
            "finding": section.finding.model_dump(),
            "retrieved_evidence": section.finding_history[-1]["retrieved_evidence"]
                if section.finding_history else [
                    {"id": p.id, **p.meta, "excerpt": p.text} for p in section.passages],
            "section_revision": section.revision,
            "finding_updated_at": section.finding_updated_at,
            "execution_status": section.execution_status,
            "audit_status": section.audit_status,
        })
    scope = state.legal_scope
    return {
        "assessment_id": state.assessment_id, "state_revision": state.revision,
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
                           "failure_reason": s.failure_reason, "audit_status": s.audit_status}
                     for key, s in state.sections.items()},
        "findings": rows, "limitations": state.limitations,
        "provenance": state.provenance,
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
            os.replace(temporary, Path(destination) / "assessment.md")
        finally:
            temporary.unlink(missing_ok=True)
    return report


def import_legacy(source: Path, state_root: Path, assessment_id: str) -> ReportState:
    """Explicit migration; source bytes and all original findings remain unmodified."""
    raw = Path(source).read_bytes()
    report = json.loads(raw.decode("utf-8"))
    sections = {}
    for row in report["findings"]:
        req = RequirementRecord.model_validate(row["requirement"])
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
