"""Synthetic profiles/companies/FDA records only; no clinical or financial evidence."""
import json
import socket
import subprocess
import sys
from dataclasses import asdict

import pytest

from vc_engine.__main__ import main
from vc_engine.comparables import compare, weights_from_dict
from vc_engine.database import connect
from vc_engine.evidence_gaps import evidence_gaps
from vc_engine.fda_client import FDAPage
from vc_engine.ingest import ingest
from vc_engine.regulatory_search import normalize
from vc_engine.regulatory_store import FDAStore
from vc_engine.startup_profile import (GAP_CATEGORIES, load_profile, profile_from_dict, profile_payload)
from test_vc_engine import write_csv


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Startup comparisons and evidence gaps must be offline")
    monkeypatch.setattr(socket, "create_connection", unexpected)


@pytest.fixture
def corpus(tmp_path):
    companies, investments, documents = [tmp_path / name for name in ("companies.csv", "investments.csv", "documents.csv")]
    write_csv(companies, "companies", [
        dict(company="Synthetic Stroke", selected_device_or_software="CT stroke triage",
             clinical_category="AI medical imaging", clinical_use_case="Stroke CT triage",
             regulatory_status_as_reported="FDA cleared per marketing", device_or_regulatory_evidence_url="https://example.invalid/claimed"),
        dict(company="Synthetic Cardiac", selected_device_or_software="AI cardiac ultrasound",
             clinical_category="AI medical imaging", clinical_use_case="Cardiac ultrasound triage"),
        dict(company="Synthetic Generic", selected_device_or_software="AI medical imaging", clinical_category="AI medical imaging"),
        dict(company="Synthetic Same Purpose Wrong Modality", selected_device_or_software="MRI stroke triage",
             clinical_use_case="Stroke MRI triage"),
        dict(company="Synthetic Pediatric", selected_device_or_software="CT stroke triage",
             clinical_use_case="Pediatric stroke CT triage"),
    ])
    write_csv(investments, "investments", [])
    write_csv(documents, "source_documents", [])
    db, fda_db = tmp_path / "vc.sqlite", tmp_path / "fda.sqlite"
    ingest(companies=companies, investments=investments, documents=documents, db=db, report_path=tmp_path / "quality.json")
    raws = [dict(k_number="K000001", device_name="Synthetic CT stroke triage", decision_code="SESE",
                 decision_description="Substantially Equivalent", applicant="Synthetic FDA applicant", openfda={"device_class": "2"}),
            dict(k_number="K000002", device_name="Synthetic CT stroke triage", decision_code="NSE", decision_description="Not Substantially Equivalent"),
            dict(k_number="K000003", device_name="Synthetic CT stroke triage")]
    page = FDAPage(dict(results=raws), "https://api.fda.gov/device/510k.json?SYNTHETIC_ONLY", "2026-10-20T00:00:00+00:00", True)
    with FDAStore(fda_db) as store:
        store.save({}, page.payload, page.source_url, page.fetched_at, [normalize(raw, page) for raw in raws])
    return dict(db=db, fda_db=fda_db)


def stroke(**updates):
    payload = dict(name="Synthetic Startup", device_name="AI medical imaging", intended_use="Stroke CT triage",
        clinical_indication="Stroke", input_modality="CT", patient_population="Adults", workflow="Emergency triage")
    payload.update(updates)
    return profile_from_dict(payload)


def test_stroke_ct_ranks_above_generic_ai_and_excludes_cardiac_modality(corpus):
    report = compare(stroke(), **corpus)
    assert report.results[0].name == "Synthetic Stroke"
    assert report.results[0].score == .75
    assert report.results[0].coverage == .75
    assert all(item.name != "Synthetic Generic" for item in report.results)
    excluded = {item.name: item for item in report.excluded_candidates}
    assert "Synthetic Cardiac" in excluded
    assert "Synthetic Same Purpose Wrong Modality" in excluded
    assert "Synthetic Pediatric" in excluded
    assert next(field for field in excluded["Synthetic Pediatric"].fields if field.field == "patient_population").status == "mismatch"
    assert any(field.field == "input_modality" and field.status == "mismatch" for field in excluded["Synthetic Cardiac"].fields)
    assert report.profile_review_status == "pending_review"
    assert all(item.confidence == "low" for item in report.results)


def test_cardiac_ultrasound_changes_top_match(corpus):
    profile = stroke(intended_use="Cardiac ultrasound triage", clinical_indication="Cardiac", input_modality="Ultrasound")
    report = compare(profile, **corpus, top_k=10)
    assert report.results[0].name == "Synthetic Cardiac"
    assert "Synthetic Stroke" in {row.name for row in report.excluded_candidates}


def test_fda_missing_intended_use_is_unknown_and_clearance_requires_actual_decision(corpus):
    report = compare(stroke(), **corpus)
    records = {row.source_id: row for row in report.results if row.kind == "fda_510k_record"}
    assert set(records) == {"K000001", "K000002", "K000003"}
    for record in records.values():
        assert next(field for field in record.fields if field.field == "intended_use").status == "unknown"
        assert next(field for field in record.fields if field.field == "clinical_indication").status == "unknown"
        assert record.score == .2 and record.coverage == .2
        assert record.regulatory["verified_by_official_record"] is False
        assert record.evidence_status == "cached"
    assert records["K000001"].regulatory["clearance_supported_by_cached_record"] is True
    assert records["K000002"].regulatory["clearance_supported_by_cached_record"] is False
    assert records["K000003"].regulatory["clearance_supported_by_cached_record"] is False
    company = next(row for row in report.results if row.kind == "company")
    assert company.regulatory["clearance_supported_by_cached_record"] is False
    assert company.evidence_status == "claimed_only"


def test_quotes_trace_to_real_csv_rows_and_stored_fda_ids(corpus):
    report = compare(stroke(), **corpus)
    company = next(row for row in report.results if row.kind == "company")
    field = next(field for field in company.fields if field.field == "intended_use")
    with connect(corpus["db"], readonly=True) as conn:
        for anchor in field.evidence:
            source = conn.execute("SELECT raw_json FROM source_rows WHERE id=?", (anchor["source_id"],)).fetchone()
            assert json.loads(source[0])[anchor["field"]] == anchor["quote"]
            assert anchor["row_number"] == 2
    assert all(field.status in {"match", "mismatch", "unknown"} for row in report.results for field in row.fields)
    assert field.profile_evidence[0]["quote"] == "Stroke CT triage"


def test_profiles_are_editable_null_preserving_and_review_bound(tmp_path):
    path = tmp_path / "startup.json"
    path.write_text(json.dumps(dict(name="  Startup ", input_modality=" ")), encoding="utf-8")
    profile = load_profile(path, reviewer="Synthetic Reviewer")
    assert profile.name == "Startup" and profile.input_modality is None
    assert "input_modality" in profile.unknown_fields and profile.review_status == "user_reviewed"
    path.write_text(json.dumps(profile_payload(profile)), encoding="utf-8")
    restored = load_profile(path)
    assert restored.review_status == "user_reviewed"
    payload = json.loads(path.read_text())
    payload["intended_use"] = "Changed purpose"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_profile(path).review_status == "pending_review"


@pytest.mark.parametrize("payload", [{"intended_use": 1}, {"unexpected": "value"}, {"unknown_fields": ["invented"]},
    {"sources": [{"source_id": "deck", "text": "Literal", "page": 0}]},
    {"sources": [{"source_id": "deck", "text": "Literal"}, {"source_id": "deck", "text": "Other"}]},
    {"sources": [{"source_id": "deck", "text": "Literal"}], "field_evidence": [{"field": "name", "source_id": "deck", "quote": "Invented"}]}])
def test_invalid_profile_data_rejected(payload):
    with pytest.raises(ValueError):
        profile_from_dict(payload)


def test_exact_profile_field_quote_is_required():
    payload = dict(intended_use="Stroke CT triage", sources=[dict(source_id="deck", text="Purpose: Stroke CT triage", page=3, chunk="paragraph-2", origin="pitch_deck")],
        field_evidence=[dict(field="intended_use", source_id="deck", quote="Purpose: Stroke CT triage")])
    profile = profile_from_dict(payload)
    assert profile.sources[0].page == 3 and profile.field_evidence[0].quote == "Purpose: Stroke CT triage"
    payload["intended_use"] = "Cardiac ultrasound"
    with pytest.raises(ValueError, match="literal value"):
        profile_from_dict(payload)


def test_gaps_never_claim_missing_clinical_evidence_in_real_world(corpus):
    gaps = evidence_gaps(stroke(name="Synthetic Stroke"), db=corpus["db"])
    categories = {gap.category: gap for gap in gaps.gaps}
    assert set(categories) == set(GAP_CATEGORIES)
    assert categories["clinical_publications"].status == "not_found_in_index"
    assert "does not mean it is absent in the real world" in categories["clinical_publications"].statement
    assert categories["regulatory_documentation"].status == "claimed_only"
    assert categories["intended_use_details"].status == "claimed_only"
    assert all(gap.status in {"supported_by_source", "claimed_only", "not_found_in_index", "conflicting", "needs_review"} for gap in gaps.gaps)


def evidence_profile(origin="publication", reviewed=True, stance="supports"):
    return dict(name="Synthetic Startup", sources=[dict(source_id="source-A", text="Synthetic study assessed external validation.", origin=origin,
        source_url="https://example.invalid/paper", page=2, chunk="study-results")],
        evidence_claims=[dict(category="external_validation", source_id="source-A", quote="Synthetic study assessed external validation.",
            stance=stance, reviewed_by="Synthetic Reviewer" if reviewed else None, review_note="Synthetic human assessment of category support" if reviewed else None)])


def test_human_reviewed_publication_source_can_support_but_deck_claim_cannot(tmp_path):
    for origin, reviewed, expected in [("publication", True, "supported_by_source"), ("publication", False, "claimed_only"), ("pitch_deck", True, "claimed_only")]:
        report = evidence_gaps(profile_from_dict(evidence_profile(origin, reviewed)), db=tmp_path / "missing.sqlite")
        gap = next(gap for gap in report.gaps if gap.category == "external_validation")
        assert gap.status == expected
        assert gap.evidence[0]["source_id"] == "source-A" and gap.evidence[0]["page"] == 2


def test_conflicts_and_challenges_have_explicit_status(tmp_path):
    payload = evidence_profile(stance="contradicts")
    report = evidence_gaps(profile_from_dict(payload), db=tmp_path / "missing.sqlite")
    assert next(gap for gap in report.gaps if gap.category == "external_validation").status == "needs_review"
    payload["evidence_claims"].append({**payload["evidence_claims"][0], "stance": "supports"})
    report = evidence_gaps(profile_from_dict(payload), db=tmp_path / "missing.sqlite")
    assert next(gap for gap in report.gaps if gap.category == "external_validation").status == "conflicting"


def test_comparable_study_not_borrowed_for_startup_gaps(corpus):
    with connect(corpus["db"]) as conn:
        conn.execute("UPDATE companies SET clinical_study_url='https://example.invalid/competing-study'")
    report = evidence_gaps(stroke(), db=corpus["db"])
    assert report.index_scope["exact_name_company_matches"] == 0
    assert next(gap for gap in report.gaps if gap.category == "clinical_publications").status == "not_found_in_index"


def test_missing_indexes_and_generic_ai_produce_empty_results_without_creation(tmp_path):
    db, fda_db = tmp_path / "absent.sqlite", tmp_path / "absent-fda.sqlite"
    result = compare(profile_from_dict(dict(device_description="AI medical imaging")), db=db, fda_db=fda_db)
    assert result.results == () and result.candidate_counts["company_index_missing"]
    assert not db.exists() and not fda_db.exists()


@pytest.mark.parametrize("weights", [{}, {"intended_use": 1}, dict(intended_use=.3, clinical_indication=.25, input_modality=.2, patient_population=.15, workflow=float("nan")),
    dict(intended_use=.3, clinical_indication=.25, input_modality=.2, patient_population=.15, workflow=.5)])
def test_invalid_weights_rejected(weights):
    with pytest.raises(ValueError):
        weights_from_dict(weights)


def test_weight_changes_are_transparent_and_unknowns_never_renormalized(corpus):
    weights = dict(intended_use=.1, clinical_indication=.1, input_modality=.6, patient_population=.1, workflow=.1)
    report = compare(stroke(), **corpus, weights=weights)
    fda = next(row for row in report.results if row.kind == "fda_510k_record")
    assert fda.score == .6 and fda.coverage == .6
    assert report.weights == weights
    assert fda.score < 1


def test_cli_outputs_stdlib_offline_and_protects_inputs(corpus, tmp_path, capsys):
    source, profile, result, gaps = [tmp_path / name for name in ("input.json", "profile.json", "compare.json", "gaps.json")]
    source.write_text(json.dumps(dict(name="Synthetic Startup", intended_use="Stroke CT triage", clinical_indication="Stroke", input_modality="CT")), encoding="utf-8")
    assert main(["profile", "--input", str(source), "--output", str(profile), "--reviewer", "Synthetic Reviewer"]) == 0
    assert main(["compare", "--profile", str(profile), "--db", str(corpus["db"]), "--fda-db", str(corpus["fda_db"]), "--output", str(result)]) == 0
    assert main(["evidence-gaps", "--profile", str(profile), "--db", str(corpus["db"]), "--output", str(gaps)]) == 0
    assert json.loads(result.read_text())["profile_review_status"] == "user_reviewed"
    proc = subprocess.run([sys.executable, "-S", "-m", "vc_engine", "compare", "--profile", str(profile), "--db", str(corpus["db"]),
        "--fda-db", str(corpus["fda_db"]), "--output", str(result)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert main(["profile", "--input", str(source), "--output", str(source)]) == 1
    assert main(["compare", "--profile", str(profile), "--db", str(corpus["db"]), "--output", str(corpus["db"])]) == 1
    assert "separate .json report" in capsys.readouterr().err


def test_queries_leave_both_databases_byte_identical(corpus):
    before = {key: path.read_bytes() for key, path in corpus.items()}
    compare(stroke(), **corpus)
    evidence_gaps(stroke(), db=corpus["db"])
    assert all(path.read_bytes() == before[key] for key, path in corpus.items())


def test_negation_and_missing_use_do_not_become_positive_matches(corpus):
    report = compare(stroke(intended_use="Not for stroke CT triage"), **corpus)
    for row in report.results:
        intended = next(field for field in row.fields if field.field == "intended_use")
        assert intended.status == "unknown" and intended.similarity == 0


def test_profile_payload_roundtrips_with_anchors():
    original = profile_from_dict(evidence_profile())
    restored = profile_from_dict(profile_payload(original))
    assert original == restored


def test_corrupt_fda_id_is_not_invented_or_returned(corpus):
    with FDAStore(corpus["fda_db"]) as store:
        with store.connection:
            store.connection.execute("UPDATE fda_records SET raw_json=? WHERE k_number='K000001'", (json.dumps(dict(k_number="K999999", device_name="CT stroke triage")),))
    report = compare(stroke(), **corpus)
    assert "K000001" not in {row.source_id for row in report.results}
    assert "K999999" not in {row.source_id for row in report.results}


def test_csv_study_url_is_only_an_unverified_reference(corpus, tmp_path):
    company_file = tmp_path / "companies-with-link.csv"
    write_csv(company_file, "companies", [dict(company="Synthetic Own", clinical_evidence_study_url="https://example.invalid/study")])
    investments, documents = tmp_path / "empty-investments.csv", tmp_path / "empty-documents.csv"
    write_csv(investments, "investments", [])
    write_csv(documents, "source_documents", [])
    ingest(companies=company_file, investments=investments, documents=documents, db=corpus["db"], report_path=tmp_path / "quality-linked.json")
    report = evidence_gaps(stroke(name="Synthetic Own"), db=corpus["db"])
    gap = next(gap for gap in report.gaps if gap.category == "clinical_publications")
    assert gap.status == "claimed_only"
    assert any(item["quote"] == "https://example.invalid/study" for item in gap.evidence)
