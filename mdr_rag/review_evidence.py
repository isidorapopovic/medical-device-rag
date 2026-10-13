"""Connect review requirements/claims to immutable legal and device raw spans."""
from .schemas import QuotedReference
from .source_buffer import SourceBuffer


def prepare_legal_anchor(section, buffer, app):
    req = section.requirement
    key = getattr(req, "legal_buffer_id", None)
    passage = None
    if key:
        # Newly extracted registers refer to the immutable extraction snapshot.
        archive = SourceBuffer(buffer.snapshots, directory=app.STATE / "source_buffer")
        try:
            passage = archive.get_passage(key)
        except ValueError:
            section.legal_anchor = None
            section.legal_anchor_issue = "referenced_legal_snapshot_unavailable_or_invalid"
            return
    if passage is None:
        parts = [part for part in app.legal_chunks(req.legal_source, {req.legal_page})
                 if part["id"] == req.legal_source_chunk_id]
        if len(parts) != 1:
            section.legal_anchor = None
            section.legal_anchor_issue = "missing_or_ambiguous_legal_chunk"
            return
        key = buffer.add_passage(parts[0])
        passage = buffer.get_passage(key)
    else:
        key = buffer.add_passage(passage)
    if (passage.kind, passage.source, passage.file_sha256, passage.page, passage.chunk_id) != (
            "legal", req.legal_source, req.legal_sha256, req.legal_page, req.legal_source_chunk_id):
        raise ValueError("Legal snapshot hash/locator does not match the requirement")
    if getattr(req, "legal_block", passage.block) != passage.block:
        raise ValueError("Legal snapshot block differs from the requirement")
    start, end = getattr(req, "legal_quote_start", None), getattr(req, "legal_quote_end", None)
    if (start is None) != (end is None):
        section.legal_anchor = None
        section.legal_anchor_issue = "incomplete_legal_quote_offsets"
        return
    offsets = (start, end) if start is not None and end is not None else None
    try:
        span = buffer.resolve_legacy_quote(key, getattr(req, "legacy_normalized_quote", None) or req.exact_quote, offsets)
        section.legal_anchor = buffer.make_link(span, req.id, "legal_basis")
        section.legal_anchor_issue = None
    except ValueError:
        section.legal_anchor = None
        section.legal_anchor_issue = "legal_quote_has_no_unique_verified_raw_span"


def validate_finding(section, buffer, app):
    """Check identities/raw spans/context membership, without claiming entailment."""
    finding = section.draft_finding.model_copy(deep=True)
    allowed = section.evidence_gate.draft_ids if section.evidence_gate else [p.id for p in section.passages]
    ids = app.validate_ids(finding.evidence_ids, [p.model_dump() for p in section.passages if p.id in allowed])
    section.claim_links, section.citation_issues = [], []
    if section.legal_anchor is None:
        section.citation_issues.append("legal_anchor_not_raw_verified")
    call = next((trace for trace in section.model_calls if trace.call_id == section.draft_call_id), None)
    if call is None or call.outcome != "completed":
        section.citation_issues.append("missing_completed_draft_call_trace")
    by_chunk = {}
    if call is not None:
        for item in call.presented:
            passage = buffer.get_passage(item.buffer_id)
            by_chunk.setdefault(passage.chunk_id, []).append(item.buffer_id)
    seen = set()
    if not finding.claims:
        section.citation_issues.append("model_provided_no_claim_span_inventory")
    for claim in finding.claims:
        if claim.claim_id in seen:
            section.citation_issues.append("duplicate_claim_id")
            claim.evidence = []
            continue
        seen.add(claim.claim_id)
        accepted = []
        for ref in claim.evidence:
            candidates = list(dict.fromkeys(by_chunk.get(ref.source_id, [])))
            # An evidence ID alone does not establish that the passage was cited.
            if len(candidates) != 1 or (ref.start is None) != (ref.end is None):
                section.citation_issues.append("invented_ambiguous_or_unpresented_citation")
                continue
            try:
                offsets = (ref.start, ref.end) if ref.start is not None else None
                span = buffer.resolve_quote(candidates[0], ref.exact_quote, offsets)
                link = buffer.make_link(span, claim.claim_id, ref.purpose)
                buffer.validate_link(link, presented=call.presented)
                if link.kind == "device" and link.chunk_id not in ids:
                    raise ValueError("Claim quote was not among finding citation IDs")
            except ValueError:
                section.citation_issues.append("invalid_raw_span_identity_role_or_context")
                continue
            accepted.append(QuotedReference(source_id=link.chunk_id, exact_quote=link.exact_quote,
                                            start=link.start, end=link.end, purpose=link.purpose))
            section.claim_links.append(link)
        claim.evidence = accepted
        if not accepted:
            section.citation_issues.append("claim_has_no_verified_cited_span")
    cited_device = {link.chunk_id for link in section.claim_links if link.kind == "device"}
    if set(ids) - cited_device:
        section.citation_issues.append("citation_id_has_no_verified_claim_quote")
    finding.evidence_ids = [key for key in ids if key in cited_device]
    if finding.status in {"supported", "partial"} and not any(
            link.purpose == "device_support" for link in section.claim_links):
        section.citation_issues.append("missing_verified_device_support_span")
    if section.citation_issues:
        finding.status = "needs_review"
        finding.explanation += " [SYSTEM: raw-span provenance requires review; see citation_issues.]"
    section.citation_issues = list(dict.fromkeys(section.citation_issues))
    return finding


def validate_obligation_coverage(section, finding):
    """Conservative checks on a model self-assessment, not semantic verification."""
    gate = section.evidence_gate
    if gate is None or gate.mode == "disabled":
        return finding
    expected = {row.obligation_id: row for row in gate.obligations}
    coverage = {row.obligation_id: row for row in finding.obligation_coverage}
    uncertain = set(coverage) != set(expected) or len(coverage) != len(finding.obligation_coverage)
    partial = False
    cited = {link.chunk_id for link in section.claim_links if link.purpose == "device_support"}
    for key, row in coverage.items():
        if key not in expected or not set(row.evidence_ids) <= set(gate.draft_ids) & cited:
            uncertain = True
            continue
        qualifiers = set(expected[key].qualifiers)
        if not set(row.addressed_qualifiers) <= qualifiers:
            uncertain = True
        if row.status in {"supported", "partial"} and not row.evidence_ids:
            uncertain = True
        if row.status == "uncertain":
            uncertain = True
        if row.status in {"partial", "not_addressed"} or (row.status == "supported" and qualifiers - set(row.addressed_qualifiers)):
            partial = True
            if row.status == "supported":
                row.status = "partial"
    if uncertain:
        finding.status = "needs_review"
        finding.explanation += " [SYSTEM: atomic obligation coverage is missing, uncertain or references unretained evidence.]"
    elif partial and finding.status == "supported":
        finding.status = "partial"
        finding.explanation += " [SYSTEM: not all atomic obligations/explicit qualifiers have supporting coverage.]"
    gate.coverage_verification = "model_self_assessed_raw_citations_only"
    return finding
