"""Fixed human-label evaluation; no model-generated ground truth or tuning."""
import json
from pathlib import Path

from .comparables import compare, company_candidates, fda_candidates
from .memo import audit_claims
from .models import DEFAULT_DB, ROOT, clean, iso_date
from .regulatory_models import DEFAULT_FDA_DB
from .startup_profile import PROFILE_FIELDS, profile_from_dict

DEFAULT_GOLD = ROOT / "eval/vc_gold_comparables.json"


def evaluate_labels(payload: dict, *, db=DEFAULT_DB, fda_db=DEFAULT_FDA_DB, memo: dict | None = None) -> dict:
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1 or not isinstance(payload.get("examples"), list):
        raise ValueError("Evaluation needs schema_version 1 and an examples list")
    examples = payload["examples"]
    if len(examples) > 100:
        raise ValueError("Evaluation supports at most 100 human-annotated profiles")
    if memo is not None and (not isinstance(memo, dict) or not isinstance(memo.get("claims"), list) or not isinstance(memo.get("sources"), dict)):
        raise ValueError("Memo audit needs a memo object with claims and sources")
    audit = audit_claims(memo["claims"], memo["sources"])[1] if memo is not None else None
    if not examples:
        return dict(status="awaiting_human_annotations", examples=0, recall_at_5=None, precision_at_5=None,
                    extraction_field_accuracy=None, citation_validity=audit,
                    limitations=["No human labels supplied; no relevance or extraction accuracy was fabricated."])
    companies, _ = company_candidates(db, 10000)
    records, _ = fda_candidates(fda_db, 10000)
    known = {row["source_id"] for row in companies + records}
    details, recalls, precisions, matched, labeled_fields = [], [], [], 0, 0
    seen = set()
    for example in examples:
        if not isinstance(example, dict) or set(example) - {"id", "profile", "relevant_ids", "candidate_kind", "reviewed_by", "reviewed_on", "annotation_notes", "expected_fields"}:
            raise ValueError("Invalid annotation fields")
        identifier = example.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError("Evaluation example IDs must be nonblank and unique")
        seen.add(identifier)
        if not isinstance(example.get("reviewed_by"), str) or not example["reviewed_by"].strip() or not isinstance(example.get("reviewed_on"), str) or iso_date(example["reviewed_on"]) is None or not isinstance(example.get("annotation_notes"), str) or not example["annotation_notes"].strip():
            raise ValueError("Each example needs human reviewer, ISO review date and annotation notes")
        relevant = example.get("relevant_ids")
        if not isinstance(relevant, list) or not all(isinstance(item, str) for item in relevant) or len(set(relevant)) != len(relevant) or set(relevant) - known:
            raise ValueError("Relevant IDs must be unique known company/FDA record IDs; stale or invented labels are rejected")
        kind = example.get("candidate_kind", "all")
        if not isinstance(kind, str) or kind not in {"all", "company", "fda_510k_record"}:
            raise ValueError("Invalid candidate_kind")
        allowed = {row["source_id"] for row in companies + records if kind == "all" or row["kind"] == kind}
        if set(relevant) - allowed:
            raise ValueError("Relevant IDs do not match candidate_kind")
        if not isinstance(example.get("profile"), dict):
            raise ValueError("Each annotation needs an embedded startup profile object")
        profile = profile_from_dict(example["profile"])
        report = compare(profile, db=db, fda_db=fda_db, top_k=100)
        returned = [row.source_id for row in report.results if kind == "all" or row.kind == kind][:5]
        hits = len(set(returned) & set(relevant))
        precision = hits / 5
        recall = hits / len(relevant) if relevant else None
        precisions.append(precision)
        if recall is not None:
            recalls.append(recall)
        expected = example.get("expected_fields", {})
        if not isinstance(expected, dict) or set(expected) - set(PROFILE_FIELDS) or any(value is not None and not isinstance(value, str) for value in expected.values()):
            raise ValueError("expected_fields must map profile fields to literal text/null")
        field_matches = sum(clean(value) == getattr(profile, field) for field, value in expected.items())
        matched += field_matches
        labeled_fields += len(expected)
        details.append(dict(id=identifier, returned_ids=returned, relevant_ids=relevant, hits=hits,
                            precision_at_5=precision, recall_at_5=recall, matched_fields=field_matches, labeled_fields=len(expected)))
    return dict(status="evaluated_human_labels", examples=len(details), recall_at_5=sum(recalls) / len(recalls) if recalls else None,
        precision_at_5=sum(precisions) / len(precisions), extraction_field_accuracy=matched / labeled_fields if labeled_fields else None,
        labeled_fields=labeled_fields, citation_validity=audit, details=details,
        limitations=["Precision@5 uses denominator 5 even when fewer results are returned. Recall is undefined for zero relevant labels.",
                     "Field accuracy is literal normalized agreement on labeled fields only; not clinical correctness or a real-deck accuracy estimate.",
                     "Human annotations are supplied, not authenticated. No model-generated labels, tuning or predictive investment accuracy."])


def evaluate_file(path: str | Path = DEFAULT_GOLD, **kwargs) -> dict:
    payload = Path(path).read_bytes()
    if len(payload) > 4 * 1024 * 1024:
        raise ValueError("Evaluation labels exceed 4 MiB")
    return evaluate_labels(json.loads(payload.decode("utf-8-sig")), **kwargs)
