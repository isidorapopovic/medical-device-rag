"""Offline lexical candidate generation and auditable, unvalidated feature ranking."""
import json
import math
import re
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from .database import connect
from .models import DEFAULT_DB, clean
from .regulatory_models import DEFAULT_FDA_DB, WARNINGS, k_number
from .regulatory_store import FDAStore
from .startup_profile import Comparable, ComparisonReport, FieldComparison, StartupProfile

DEFAULT_WEIGHTS = {"intended_use": .30, "clinical_indication": .25, "input_modality": .20,
                   "patient_population": .15, "workflow": .10}
STOP = set("a an the and or of to in on for with by as is are this that our ai artificial intelligence medical clinical imaging image software device system platform technology analysis solution using enabled based powered automated learning deep detection diagnostic".split())
# Small, explicit lexical vocabulary, not a clinical ontology or equivalence model.
ALIASES = {"echocardiography": "ultrasound", "echocardiographic": "ultrasound", "echo": "ultrasound",
           "cardiology": "cardiac", "heart": "cardiac", "computed tomography": "ct",
           "magnetic resonance": "mri", "adults": "adult", "children": "pediatric",
           "paediatric": "pediatric", "child": "pediatric", "patients": "patient"}
MODALITIES = {"ct", "mri", "ultrasound", "ecg", "eeg", "xray", "pathology", "fundus"}
POPULATIONS = {"adult", "pediatric", "neonatal", "infant", "pregnant"}
NEGATION = re.compile(r"\b(no|not|without|exclude[sd]?|excluding)\b", re.I)


def tokens(value: str | None) -> set[str]:
    text = (value or "").casefold().replace("x-ray", "xray")
    for old, new in ALIASES.items():
        text = re.sub(r"\b" + re.escape(old) + r"\b", new, text)
    return set(re.findall(r"\b[a-z0-9]{2,}\b", text)) - STOP


def weights_from_dict(values: dict | None = None) -> dict[str, float]:
    if values is None:
        return dict(DEFAULT_WEIGHTS)
    if not isinstance(values, dict) or set(values) != set(DEFAULT_WEIGHTS):
        raise ValueError("Weights must provide exactly: " + ", ".join(DEFAULT_WEIGHTS))
    if any(type(value) not in {int, float} or not math.isfinite(value) or value < 0 for value in values.values()):
        raise ValueError("Weights must be finite, nonnegative numbers")
    if not math.isclose(sum(values.values()), 1, abs_tol=1e-8):
        raise ValueError("Feature weights must sum to 1")
    return {key: float(values[key]) for key in DEFAULT_WEIGHTS}


def _urls(raw: dict) -> tuple[str, ...]:
    urls = set()
    for value in raw.values():
        if isinstance(value, str):
            urls.update(re.findall(r"https?://[^\s<>\"|]+", value))
    return tuple(sorted(urls))


def _company_evidence(conn, row: dict, raw: dict, field: str) -> tuple[dict, ...]:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        return ()
    matches = conn.execute("""SELECT c.source_row_id,c.field_name,c.raw_value,r.input_filename,
        r.file_sha256,r.row_number FROM source_claims c JOIN source_rows r ON r.id=c.source_row_id
        WHERE c.entity_table='companies' AND c.entity_id=? AND c.field_name=? AND c.raw_value=?
        ORDER BY c.source_row_id LIMIT 4""", (row["id"], field, value)).fetchall()
    return tuple(dict(source_id=item["source_row_id"], field=field, quote=item["raw_value"],
                      input_filename=item["input_filename"], row_number=item["row_number"],
                      file_sha256=item["file_sha256"], status="claimed_only") for item in matches)


def company_candidates(db: str | Path, cap: int) -> tuple[list[dict], dict]:
    if not Path(db).exists():
        return [], {"companies_scanned": 0, "company_index_missing": True, "company_scan_truncated": False}
    candidates = []
    with closing(connect(db, readonly=True)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        for stored in conn.execute("SELECT * FROM companies ORDER BY id LIMIT ?", (cap,)):
            row, raw = dict(stored), json.loads(stored["raw_json"])
            use = clean(raw.get("clinical_use_case"))
            descriptive_fields = [key for key in ("clinical_use_case", "selected_device_or_software") if clean(raw.get(key))]
            descriptive = " | ".join(raw[key] for key in descriptive_fields)
            modality = descriptive if tokens(descriptive) & MODALITIES else None
            population = use if tokens(use) & POPULATIONS else None
            values = dict(intended_use=use, clinical_indication=use, input_modality=modality,
                          patient_population=population, workflow=None,
                          regulatory_classification=clean(raw.get("regulatory_status_as_reported")))
            evidence = {dimension: _company_evidence(conn, row, raw, "clinical_use_case")
                        for dimension in ("intended_use", "clinical_indication", "patient_population")}
            evidence["input_modality"] = tuple(anchor for key in descriptive_fields for anchor in _company_evidence(conn, row, raw, key))
            evidence["workflow"] = ()
            evidence["regulatory_classification"] = _company_evidence(conn, row, raw, "regulatory_status_as_reported")
            candidates.append(dict(source_id=row["id"], kind="company", name=row["name"], values=values,
                evidence=evidence, raw=raw, links=_urls(raw), evidence_status="claimed_only",
                regulatory={"clearance_supported_by_cached_record": False,
                            "status": "Company-reported claims only; no product-specific FDA linkage established.",
                            "claimed_status": values["regulatory_classification"]},
                search_text=" ".join(value for key, value in raw.items() if key in {
                    "company", "selected_device_or_software", "clinical_category", "clinical_use_case"} and isinstance(value, str))))
    return candidates, {"companies_scanned": len(candidates), "company_index_missing": False, "company_scan_truncated": count > cap}


def fda_candidates(db: str | Path, cap: int) -> tuple[list[dict], dict]:
    if not Path(db).exists():
        return [], {"fda_records_scanned": 0, "fda_cache_missing": True, "fda_scan_truncated": False}
    candidates = []
    with FDAStore(db, readonly=True) as store:
        count = store.connection.execute("SELECT COUNT(*) FROM fda_records").fetchone()[0]
        rows = store.connection.execute("SELECT * FROM fda_records ORDER BY k_number LIMIT ?", (cap,))
        for stored in rows:
            row, raw = dict(stored), json.loads(stored["raw_json"])
            try:
                if k_number(raw.get("k_number", "")) != row["k_number"]:
                    continue
            except (ValueError, AttributeError):
                continue
            name = clean(raw.get("device_name")) if isinstance(raw.get("device_name"), str) else None
            harmonized = raw.get("openfda") if isinstance(raw.get("openfda"), dict) else {}
            classification = harmonized.get("device_class")
            classification = str(classification) if type(classification) in {str, int} else None
            values = dict(intended_use=None, clinical_indication=None, input_modality=name if tokens(name) & MODALITIES else None,
                          patient_population=None, workflow=None, regulatory_classification=classification)
            anchor = dict(source_id=row["k_number"], field="device_name", quote=raw.get("device_name"),
                          source_url=row["source_url"], source_checked_at=row["checked_at"], status="cached")
            decision = raw.get("decision_code") == "SESE" and raw.get("decision_description") == "Substantially Equivalent"
            official = urlsplit(row["source_url"]).scheme == "https" and urlsplit(row["source_url"]).netloc == "api.fda.gov"
            supported = bool(decision and official and row["checked_at"] and row["retrieval_status"] == "fetched_official")
            candidates.append(dict(source_id=row["k_number"], kind="fda_510k_record", name=name or row["k_number"],
                values=values, evidence={key: (anchor,) if key == "input_modality" and values[key] else () for key in values},
                raw=raw, links=(row["source_url"],), evidence_status="cached",
                regulatory=dict(clearance_supported_by_cached_record=supported,
                    status="Substantially Equivalent decision reported in cached official record" if supported else "Clearance not established by this cached record",
                    decision_code=raw.get("decision_code"), decision_description=raw.get("decision_description"),
                    fetched_at=row["fetched_at"], source_checked_at=row["checked_at"], verified_by_official_record=False),
                search_text=" ".join(str(raw.get(key) or "") for key in ("device_name", "applicant", "product_code"))))
    return candidates, {"fda_records_scanned": len(candidates), "fda_cache_missing": False, "fda_scan_truncated": count > cap}


def _dimension(field: str, value: str | None, candidate: dict, weight: float) -> FieldComparison:
    other, anchors = candidate["values"][field], candidate["evidence"].get(field, ())
    status, similarity, reason = "unknown", 0.0, "A value or usable field-specific source is missing."
    if value and other and anchors:
        left, right = tokens(value), tokens(other)
        if field == "input_modality":
            left, right = left & MODALITIES, right & MODALITIES
        elif field == "patient_population":
            left, right = left & POPULATIONS, right & POPULATIONS
        if NEGATION.search(value) or NEGATION.search(other):
            reason = "Negated/exclusion language needs review; lexical agreement was not assumed."
        elif left and right:
            similarity = len(left & right) / len(left)
            status = "match" if similarity >= .5 else "mismatch" if not left & right else "unknown"
            reason = "Literal lexical overlap: " + (", ".join(sorted(left & right)) or "none") + "; not confirmed clinical equivalence."
            if status != "match":
                similarity = 0.0
    return FieldComparison(field, status, value, other, round(similarity, 6), weight, reason, anchors)


def _profile_evidence(profile: StartupProfile, field: str) -> tuple[dict, ...]:
    sources = {source.source_id: source for source in profile.sources}
    anchors = tuple(dict(source_id=anchor.source_id, field=field, quote=anchor.quote,
        source_url=sources[anchor.source_id].source_url, page=sources[anchor.source_id].page,
        chunk=sources[anchor.source_id].chunk, status="claimed_only")
        for anchor in profile.field_evidence if anchor.field == field)
    value = getattr(profile, field)
    if anchors or value is None:
        return anchors
    return (dict(source_id="startup:" + (profile.input_sha256 or profile.fingerprint), field=field,
                 quote=value, status="claimed_only", origin="profile_declaration"),)


def compare(profile: StartupProfile, *, db: str | Path = DEFAULT_DB, fda_db: str | Path = DEFAULT_FDA_DB,
            top_k: int = 5, weights: dict | None = None, scan_cap: int = 10000) -> ComparisonReport:
    if type(top_k) is not int or not 1 <= top_k <= 100 or type(scan_cap) is not int or not 1 <= scan_cap <= 10000:
        raise ValueError("top_k must be 1–100 and scan_cap 1–10000")
    weights = weights_from_dict(weights)
    companies, company_counts = company_candidates(db, scan_cap)
    records, fda_counts = fda_candidates(fda_db, scan_cap)
    query_text = " ".join(getattr(profile, key) or "" for key in (
        "device_name", "device_description", "intended_use", "clinical_indication", "input_modality", "patient_population", "workflow"))
    query_tokens = tokens(query_text)
    results, excluded = [], []
    generated = 0
    for candidate in companies + records:
        if candidate["kind"] == "company" and profile.name and profile.name.casefold() == candidate["name"].casefold():
            continue
        overlap = query_tokens & tokens(candidate["search_text"])
        if not overlap:
            continue
        generated += 1
        dimensions = tuple(replace(_dimension(key, getattr(profile, key), candidate, weight),
                           profile_evidence=_profile_evidence(profile, key)) for key, weight in weights.items())
        # Regulatory class cannot be inferred from a profile's reported clearance/CE text.
        classification = FieldComparison("regulatory_classification", "unknown", profile.claimed_regulatory_status,
            candidate["values"]["regulatory_classification"], 0, 0,
            "No structured jurisdiction-specific reviewed startup classification is supplied; no equivalence inferred.",
            candidate["evidence"].get("regulatory_classification", ()))
        score = sum(item.weight * item.similarity for item in dimensions)
        coverage = sum(item.weight for item in dimensions if item.status != "unknown")
        blocked = any(item.status == "mismatch" for item in dimensions if item.field in {
            "intended_use", "clinical_indication", "input_modality", "patient_population"})
        reasons = tuple(f"{item.field}: {item.status} ({item.weight:g} weight; contribution {item.weight * item.similarity:.3f})." for item in dimensions)
        uncertainty = ("Baseline lexical heuristics; scores/coverage are not calibrated clinical confidence.",
            "Profile review: " + profile.review_status + ".", "Regulatory classification comparability is unknown.")
        if candidate["kind"] == "company":
            uncertainty += ("Intended use and indication reuse the CSV clinical_use_case claim; they are not independent corroboration.",)
        result = Comparable(candidate["source_id"], candidate["kind"], candidate["name"], round(score, 6), round(coverage, 6),
            "low" if coverage < .5 or profile.review_status != "user_reviewed" else "unvalidated_heuristic",
            (*dimensions, classification), candidate["evidence_status"], candidate["links"], candidate["regulatory"], reasons,
            uncertainty, blocked)
        (excluded if blocked else results).append(result)
    results.sort(key=lambda item: (-item.score, -item.coverage, item.kind, item.source_id))
    excluded.sort(key=lambda item: item.source_id)
    counts = {**company_counts, **fda_counts, "generated": generated, "excluded": len(excluded), "eligible": len(results),
              "returned": min(top_k, len(results)), "excluded_returned": min(top_k, len(excluded))}
    return ComparisonReport(profile.fingerprint, profile.review_status, tuple(results[:top_k]), tuple(excluded[:top_k]), weights, counts,
        ("Review/edit startup fields before relying on matches. Profiles and CSVs contain unverified claims.", *WARNINGS),
        ("Offline lexical mode; no model calls, vector index changes, network requests or new FDA checks.",
         "Unknown dimensions contribute zero without renormalizing weights; coverage measures observed dimensions, not reliability.",
         "Only the scanned company/FDA subset is searched; scan/top-k caps and lexical vocabulary can omit relevant devices.",
         "Known lexical purpose/indication/modality/population mismatches are excluded from top matches and shown separately."))
