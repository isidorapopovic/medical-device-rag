"""Source-status evidence inventory for the startup itself, never its comparables."""
import json
from contextlib import closing
from pathlib import Path

from .database import connect
from .models import DEFAULT_DB, clean
from .queries import provenance
from .startup_profile import GAP_CATEGORIES, EvidenceGap, EvidenceGapReport, StartupProfile

LABELS = {"clinical_publications": "clinical publication", "external_validation": "external validation",
          "prospective_evidence": "prospective study", "comparator_studies": "comparator study",
          "reimbursement_evidence": "reimbursement", "regulatory_documentation": "regulatory documentation",
          "intended_use_details": "device-specific intended use"}


def evidence_gaps(profile: StartupProfile, *, db: str | Path = DEFAULT_DB) -> EvidenceGapReport:
    source_map = {source.source_id: source for source in profile.sources}
    own_rows, own_evidence = [], []
    index_missing = not Path(db).exists()
    if not index_missing:
        with closing(connect(db, readonly=True)) as conn:
            if profile.name:
                own_rows = [dict(row) for row in conn.execute("SELECT * FROM companies WHERE name_key=?", (profile.name.casefold(),))]
            for row in own_rows:
                for claim in provenance(conn, "companies", row["id"]):
                    if claim["field_name"] in {"clinical_evidence_study_url", "regulatory_status_as_reported", "device_or_regulatory_evidence_url", "clinical_use_case"}:
                        own_evidence.append(dict(source_id=claim["source_row_id"], field=claim["field_name"],
                            quote=claim["raw_value"], input_filename=claim["input_filename"], row_number=claim["row_number"],
                            file_sha256=claim["file_sha256"], status="claimed_only"))
    raw_rows = [json.loads(row["raw_json"]) for row in own_rows]
    gaps = []
    for category in GAP_CATEGORIES:
        evidence = []
        claims = [claim for claim in profile.evidence_claims if claim.category == category]
        for claim in claims:
            source = source_map[claim.source_id]
            evidence.append(dict(source_id=source.source_id, quote=claim.quote, source_url=source.source_url,
                page=source.page, chunk=source.chunk, source_origin=source.origin, stance=claim.stance,
                reviewed_by=claim.reviewed_by, review_note=claim.review_note,
                status="supported_by_source" if claim.reviewed_by and source.origin in {"publication", "official_document"} and claim.stance == "supports" else "claimed_only"))
        field = "intended_use" if category == "intended_use_details" else "claimed_regulatory_status" if category == "regulatory_documentation" else None
        value = getattr(profile, field) if field else None
        if value:
            evidence.append(dict(source_id="startup:" + (profile.input_sha256 or profile.fingerprint),
                field=field, quote=value, status="claimed_only", source_origin="profile_declaration"))
        indexed_fields = {"clinical_publications": {"clinical_evidence_study_url"},
                          "regulatory_documentation": {"regulatory_status_as_reported", "device_or_regulatory_evidence_url"},
                          "intended_use_details": {"clinical_use_case"}}.get(category, set())
        evidence.extend(item for item in own_evidence if item["field"] in indexed_fields)
        indexed_claim = any(clean(raw.get(key)) for raw in raw_rows for key in indexed_fields)
        stances = {claim.stance for claim in claims}
        if stances == {"supports", "contradicts"}:
            status = "conflicting"
            statement = f"Indexed source claims disagree about {LABELS[category]}; resolve the explicit conflicting claims."
        elif "contradicts" in stances:
            status = "needs_review"
            statement = f"A source explicitly challenges {LABELS[category]}; human review is required."
        elif any(item["status"] == "supported_by_source" for item in evidence):
            status = "supported_by_source"
            statement = f"An exact source quote has a recorded human support assessment for {LABELS[category]}; scope and study quality still need review."
        elif claims or value or indexed_claim:
            status = "claimed_only"
            statement = f"A declaration or indexed reference mentions {LABELS[category]}; independent supporting documentation has not been established here."
        else:
            status = "not_found_in_index"
            statement = f"Supporting {LABELS[category]} evidence was not found in the inspected startup profile and exact-name company records; this does not mean it is absent in the real world."
        gaps.append(EvidenceGap(category, status, statement, tuple(evidence),
            (f"Review device-specific {LABELS[category]} sources, their scope, dates and supporting passages.",
             "Do not borrow supporting evidence or regulatory status from a comparable company/device.")))
    return EvidenceGapReport(profile.fingerprint, profile.review_status, tuple(gaps),
        dict(company_index_missing=index_missing, exact_name_company_matches=len(own_rows),
             profile_sources=len(profile.sources), scope="Provided startup sources and exact-name local company records only"),
        ("No network, PubMed lookup, publication verification or document extraction was performed.",
         "supported_by_source means a literal anchored quote with a supplied human review record, not independent verification or study-quality validation.",
         "Pitch-deck/user-supplied assertions remain claimed_only even with a review note.",
         "not_found_in_index describes this bounded local inventory, never absence of real-world evidence.",
         "Review/edit the startup profile before relying on the report; review status: " + profile.review_status + "."))
