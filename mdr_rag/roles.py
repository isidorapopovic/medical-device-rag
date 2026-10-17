"""Six explicit local roles sharing the existing retrieval and grounding engines."""
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .applicability import ApplicabilityAnalyst
from .claim_audit import CitationAuditor as RawCitationAuditor
from .report_state import RequirementRecord, RetrievedPassage, fingerprint, export_report
from .schemas import Finding, StructuredFinding
from .source_buffer import ClaimEvidenceLink, SourceBuffer
from .evidence_gate import GateDecision


class VersionedRegister(BaseModel):
    model_config = ConfigDict(extra="allow")
    requirements: list[RequirementRecord]
    register_schema_version: Literal[1] = 1
    register_fingerprint: str = ""


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[str]
    candidates: list[RetrievedPassage]
    retrieved_buffer_ids: list[str]
    provenance: dict | None
    gate: GateDecision | None


class AuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    performed: bool = False
    passed: bool
    issues: list[str]
    links: list[ClaimEvidenceLink]


class ReviewedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: StructuredFinding | None
    finding: Finding | None
    audit: AuditResult
    reviewer_records: list[dict]
    repair_attempts: int = Field(ge=0, le=1)


class ReportExport(BaseModel):
    json_path: str
    markdown_path: str
    assessed_requirements: int
    total_requirements: int
    partial_run: bool


class RequirementAnalyst:
    def register(self, data):
        output = VersionedRegister.model_validate(data)
        ids = [r.id for r in output.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate requirement IDs in register")
        expected = fingerprint([r.model_dump() for r in output.requirements])
        if output.register_fingerprint and output.register_fingerprint != expected:
            raise ValueError("Requirement register fingerprint mismatch")
        output.register_fingerprint = expected
        return output

    def anchor(self, section, buffer, app):
        from .review_evidence import prepare_legal_anchor
        prepare_legal_anchor(section, buffer, app)

    def extract(self, app, pages, filename):
        from .requirement_analyst import extract_register
        return self.register(extract_register(app, pages, filename))


class EvidenceRetriever:
    def run(self, stage, job, section, buffer_factory):
        if stage not in {"queries", "retrieval", "gate"}:
            raise ValueError("Evidence Retriever cannot draft, assess scope or publish")
        job()
        return self.result(section, buffer_factory())

    def result(self, section, buffer):
        for key in section.retrieved_buffer_ids:
            buffer.get_passage(key)
        return RetrievalResult(queries=section.queries, candidates=section.passages,
            retrieved_buffer_ids=section.retrieved_buffer_ids, provenance=section.retrieval_trace,
            gate=section.evidence_gate)


class CitationAuditor:
    def audit(self, draft, buffer, presented):
        links, issues = RawCitationAuditor(buffer, presented).claims(draft.claims)
        return AuditResult(performed=True, passed=not issues, issues=issues, links=links)


class EvidenceReviewer:
    def run(self, stage, job, section):
        if stage not in {"draft", "validation"}:
            raise ValueError("Evidence Reviewer cannot extract, retrieve or publish")
        job()
        return self.result(section)

    def result(self, section):
        return ReviewedFinding(draft=section.structured_draft, finding=section.validated_finding,
            audit=AuditResult(performed=section.validated_finding is not None and section.structured_draft is not None,
                              passed=section.validated_finding is not None and section.structured_draft is not None and not section.citation_issues, issues=section.citation_issues,
                              links=section.claim_links), reviewer_records=section.validation_records,
            repair_attempts=section.repair_attempts)


class ReportWriter:
    def write(self, state, directory, *, historical=False):
        report = export_report(state, directory, historical=historical)
        return ReportExport(json_path=str(Path(directory) / "assessment.json"),
            markdown_path=str(Path(directory) / "assessment.md"),
            assessed_requirements=report["assessed_requirements"],
            total_requirements=report["total_extracted_requirements"], partial_run=report["partial_run"])


class AssessmentOrchestrator:
    def __init__(self):
        self.requirement_analyst = RequirementAnalyst()
        self.applicability_analyst = ApplicabilityAnalyst()
        self.evidence_retriever = EvidenceRetriever()
        self.evidence_reviewer = EvidenceReviewer()
        self.citation_auditor = CitationAuditor()
        self.report_writer = ReportWriter()

    def stage(self, stage, section, config, profile, app, state, persist, work):
        buffer = SourceBuffer(state.source_buffer)
        if stage == "applicability":
            self.requirement_analyst.anchor(section, buffer, app)
            result = self.applicability_analyst.assess(section.requirement, section.legal_anchor, profile,
                **({"app": app} if state.legal_scope.get("registry_selection")
                   and getattr(section.requirement, "registry_edition_id", None) else {}))
            section.applicability_result = result
            section.applicability, section.applicability_reason = result.status, result.reason
            state.source_buffer = buffer.snapshots
            return result
        job = lambda: work(stage, section, config, profile, app, state, persist)
        if stage in {"queries", "retrieval", "gate"}:
            return self.evidence_retriever.run(stage, job, section, lambda: SourceBuffer(state.source_buffer))
        if stage in {"draft", "validation"}:
            result = self.evidence_reviewer.run(stage, job, section)
            if stage == "validation" and section.structured_draft is not None and not section.citation_issues:
                call = next(c for c in section.model_calls if c.call_id == section.draft_call_id)
                audit = self.citation_auditor.audit(section.structured_draft, SourceBuffer(state.source_buffer), call.presented)
                if not audit.passed:
                    raise ValueError("Deterministic role audit disagrees with the validated finding")
            return result
        job()
        return section.finding
