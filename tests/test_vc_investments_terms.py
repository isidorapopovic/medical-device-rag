"""Synthetic data and mocked document HTTP only; not financial or clinical evidence."""
import copy
import hashlib
import json
import socket
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
import requests

from vc_engine.__main__ import main
from vc_engine.database import connect
from vc_engine.ingest import ingest
from vc_engine.investment_comparables import InvestmentFilters, query_investments
from vc_engine.queries import stats
from vc_engine.terms import DEFAULT_TERMS, load_terms, lookup_term, validate_registry
from vc_engine.vc_documents import fetch_document, public_https_url, query_catalog
from test_vc_engine import write_csv


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Task 04 unit tests must never use network")
    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(requests.Session, "get", unexpected)


@pytest.fixture
def inputs(tmp_path):
    companies, investments, documents = [tmp_path / name for name in ("companies.csv", "investments.csv", "documents.csv")]
    company = dict(company="  Heart  AI ", headquarters_country="Germany", selected_device_or_software="Synthetic Ultrasound",
        clinical_category="Cardiology", clinical_use_case="Cardiac ultrasound triage", dealroom_reported_total_funding_usd_millions="12.5",
        funding_source_url="https://example.invalid/company-funding", research_date="2026-10-17")
    write_csv(companies, "companies", [company, {**company, "company": "heart ai"}])
    write_csv(investments, "investments", [dict(investor="Fund A", investor_country="France", company="HEART   AI",
        product_or_platform="Synthetic Ultrasound", product_category="Cardiac software", reported_round_amount="10", reported_round_currency="EUR million",
        round_stage="Seed", round_date="2025-01-02", amount_type="Total financing round", fund_check_disclosure="Not disclosed",
        verification_level="Input claims confirmed", fund_portfolio_source="https://example.invalid/portfolio",
        round_announcement_source="https://example.invalid/round", as_of_date="2026-10-17"),
        dict(investor="Fund B", company="Uncataloged Company", product_category="CT triage")])
    write_csv(documents, "source_documents", [dict(source_id="SYN-01", fund_name="Document-only Fund", document_title="Synthetic report",
        direct_document_or_page_url="https://example.invalid/report", expected_extractable_fields="NAV; DPI; investor checks",
        verification_status="CSV says verified", research_priority="High", format="TXT", observed_2026_10_16="2026-10-16")])
    params = dict(companies=companies, investments=investments, documents=documents, db=tmp_path / "vc.sqlite", report_path=tmp_path / "quality.json")
    ingest(**params)
    return params


def test_all_seed_terms_aliases_and_caveats():
    terms = load_terms()
    assert len(terms) == 31 and all(term.status == "draft" for term in terms)
    assert lookup_term("mOiC").id == "MOIC"
    assert lookup_term("  annual   recurring revenue ").id == "ARR"
    assert "not total annual revenue" in " ".join(lookup_term("ARR").common_misinterpretations).lower()
    assert "convertible" in " ".join(lookup_term("pre-money").formula["caveats"]).lower()
    assert "option-pool" in " ".join(lookup_term("post money").formula["caveats"]).lower()
    assert lookup_term("IRR").unit == "annualized_percentage"
    assert lookup_term("MOIC").unit == "multiple"
    assert lookup_term("IRR").formula is None
    with pytest.raises(ValueError, match="Unknown VC term"):
        lookup_term("nonexistent")


def registry():
    return dict(schema_version=1, terms=[asdict(load_terms()[0])])


def valid_registry():
    # JSON conversion makes the public dataclass tuples valid editable arrays.
    return json.loads(json.dumps(registry()))


@pytest.mark.parametrize("change", ["id", "alias", "duplicate_alias", "unit", "formula_call", "formula_unit", "formula_zero", "review"])
def test_registry_rejects_invalid_schema(change):
    payload = valid_registry()
    term = payload["terms"][0]
    if change == "id":
        payload["terms"].append(copy.deepcopy(term))
    elif change == "alias":
        payload["terms"].append({**copy.deepcopy(term), "id": "other", "label": "Other"})
    elif change == "duplicate_alias":
        term["aliases"] = ["duplicate", "DUPLICATE"]
    elif change == "unit":
        term["unit"] = "guessed_dollars"
    elif change == "formula_call":
        term["formula"]["expression"] = "__import__('os').system('bad')"
    elif change == "formula_unit":
        term["formula"]["variables"]["funding_round_amount"] = "months"
    elif change == "formula_zero":
        term["formula"]["expression"] = "post_money_valuation / 0"
    else:
        term["status"] = "reviewed"
    with pytest.raises(ValueError):
        validate_registry(payload)


def test_duplicate_yaml_keys_fail_and_review_metadata_required(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("schema_version: 1\nschema_version: 1\nterms: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_terms(path)
    payload = valid_registry()
    payload["terms"][0].update(status="reviewed", reviewed_by="Synthetic Reviewer", review_note="Synthetic review", reviewed_on="2026-10-20")
    assert validate_registry(payload)[0].status == "reviewed"


def test_normalized_join_amounts_currency_and_original_verification(inputs):
    result = query_investments(db=inputs["db"], filters=InvestmentFilters(company="heart ai")).results[0]
    assert result.join_status == "exact_normalized_name" and result.company_country == "Germany"
    assert result.investor_country == "France"
    assert (result.reported_total_round_amount.amount, result.reported_total_round_amount.currency) == (10_000_000, "EUR")
    assert result.individual_fund_check.amount is None and result.individual_fund_check.currency is None
    assert (result.company_cumulative_funding.amount, result.company_cumulative_funding.currency) == (12_500_000, "USD")
    assert result.company_cumulative_funding.source_url == "https://example.invalid/company-funding"
    assert result.evidence_status == "claimed_only" and result.relationship_verification_note == "Input claims confirmed"
    assert "individual_fund_check" in result.missing_data
    assert result.field_provenance and not result.join_review
    assert any(item["entity_table"] == "companies" and item["field"] == "dealroom_reported_total_funding_usd_millions" for item in result.field_provenance)
    assert not query_investments(db=inputs["db"]).ambiguous_company_keys


@pytest.mark.parametrize("field,value", [("headquarters_country", "Spain"), ("selected_device_or_software", "Different CT product")])
def test_material_name_collisions_withhold_company_facts(inputs, field, value):
    company = dict(company="Heart AI", headquarters_country="Germany", selected_device_or_software="Synthetic Ultrasound")
    write_csv(inputs["companies"], "companies", [company, {**company, field: value}])
    ingest(**inputs)
    report = query_investments(db=inputs["db"], filters=InvestmentFilters(company="Heart AI"))
    row = report.results[0]
    assert row.join_status == "ambiguous_name" and row.join_review
    assert row.company_cumulative_funding.amount is None and row.company_country is None and row.clinical_use_case is None
    assert report.ambiguous_company_keys[0]["conflicting_fields"]
    assert row.reported_total_round_amount.amount == 10_000_000


@pytest.mark.parametrize("field,value", [("specialty", "cardiology"), ("indication", "ultrasound"), ("country", "germany"),
    ("investor_country", "france"), ("stage", "seed"), ("product_category", "cardiac"), ("investor", "fund a"), ("keyword", "Ultrasound")])
def test_investment_filters(inputs, field, value):
    report = query_investments(db=inputs["db"], filters=InvestmentFilters(**{field: value}))
    assert report.total_matching == 1 and report.results[0].investor == "Fund A"


def test_unknown_company_profile_and_no_fuzzy_or_document_investor_inference(inputs):
    report = query_investments(db=inputs["db"])
    uncataloged = next(row for row in report.results if row.company == "Uncataloged Company")
    assert uncataloged.join_status == "no_company_profile" and uncataloged.company_cumulative_funding.amount is None
    assert not query_investments(db=inputs["db"], filters=InvestmentFilters(company="Heart-AI")).results
    assert not query_investments(db=inputs["db"], filters=InvestmentFilters(investor="Document-only Fund")).results
    assert not query_investments(db=inputs["db"], filters=InvestmentFilters(country="France")).results


def test_catalog_displays_expected_fields_not_extracted_values(inputs):
    before = inputs["db"].read_bytes()
    entries = query_catalog(db=inputs["db"], keyword="NAV", fund="document-only fund", priority="high")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.expected_extractable_fields == "NAV; DPI; investor checks"
    assert entry.evidence_status == "unverified_link_catalog" and entry.verification_status_as_reported == "CSV says verified"
    assert entry.field_provenance and "NAV" not in asdict(entry)
    assert before == inputs["db"].read_bytes()


class Response:
    def __init__(self, content=b"SYNTHETIC report only. NAV: fictional, not extracted facts.", status=200, headers=None):
        self.content, self.status_code = content, status
        self.headers = {"Content-Type": "text/plain", **(headers or {})}
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *items):
        self.items, self.calls = list(items), []

    def get(self, url, **kwargs):
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        self.calls.append(url)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def public_resolver(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]


def fetch(inputs, tmp_path, session, **kwargs):
    return fetch_document("SYN-01", db=inputs["db"], output_dir=tmp_path / "downloads", online=True,
                          session=session, resolver=public_resolver, **kwargs)


def test_document_fetch_is_explicit_and_idempotent_bytes_not_financial_facts(inputs, tmp_path):
    with pytest.raises(ValueError, match="explicit --online"):
        fetch_document("SYN-01", db=inputs["db"], output_dir=tmp_path / "downloads")
    assert not (tmp_path / "downloads").exists()
    before = inputs["db"].read_bytes()
    first = fetch(inputs, tmp_path, Session(Response()))
    second = fetch(inputs, tmp_path, Session(Response()))
    assert first["download_status"] == "downloaded" and first["http_status"] == 200
    assert first["checksum_sha256"] == second["checksum_sha256"]
    assert first["attempt_id"] != second["attempt_id"] and first["observed_at"]
    assert len(list((tmp_path / "downloads/files").iterdir())) == 1
    assert len(list((tmp_path / "downloads/attempts").iterdir())) == 2
    assert first["extraction_status"] == "not_attempted"
    assert before == inputs["db"].read_bytes()
    assert not query_investments(db=inputs["db"], filters=InvestmentFilters(investor="Document-only Fund")).results


@pytest.mark.parametrize("item", [Response(status=404), requests.Timeout(), Response(content=b"x" * 200)])
def test_document_failures_are_logged(inputs, tmp_path, item):
    result = fetch(inputs, tmp_path, Session(item), max_bytes=100)
    assert result["download_status"] == "failed" and result["errors"]
    assert result["checksum_sha256"] is None
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["observed_at"] and manifest["url"] == "https://example.invalid/report"


def test_download_extraction_preserves_passages_without_financial_fact_creation(inputs, tmp_path):
    result = fetch(inputs, tmp_path, Session(Response()), extract=True)
    assert result["download_status"] == "downloaded" and result["extraction_status"] == "parsed"
    extraction = json.loads(Path(result["extraction_path"]).read_text())
    assert extraction["units"][0]["raw_text"].startswith("SYNTHETIC")
    failed = fetch(inputs, tmp_path, Session(Response(content=b"<html>Index page</html>", headers={"Content-Type": "text/html"})), extract=True)
    assert failed["download_status"] == "downloaded" and failed["extraction_status"] == "failed"
    assert failed["extraction_errors"]


@pytest.mark.parametrize("url", ["http://example.com/report", "https://127.0.0.1/report", "file:///private", "https://name:password@example.com/file"])
def test_private_nonhttps_and_credentials_rejected(url):
    def resolver(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host if host == "127.0.0.1" else "8.8.8.8", 443))]
    with pytest.raises(ValueError):
        public_https_url(url, resolver=resolver)


def test_redirects_checked_logged_and_bounded(inputs, tmp_path):
    redirect = Response(status=302, headers={"Location": "https://127.0.0.1/private"})
    def resolver(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1" if host == "127.0.0.1" else "8.8.8.8", 443))]
    session = Session(redirect)
    result = fetch_document("SYN-01", db=inputs["db"], output_dir=tmp_path / "blocked", online=True, session=session, resolver=resolver)
    assert result["download_status"] == "failed" and len(session.calls) == 1
    assert redirect.closed and result["http_status"] == 302
    redirects = Session(*(Response(status=302, headers={"Location": "/again"}) for _ in range(4)))
    result = fetch(inputs, tmp_path, redirects)
    assert result["download_status"] == "failed" and len(redirects.calls) == 4


def test_cli_glossary_investments_catalog_and_profile_integration(inputs, tmp_path, capsys):
    for args in (["terms", "list"], ["terms", "show", "MOIC"], ["terms", "search", "revenue"], ["terms", "validate"]):
        assert main(args) == 0
        assert "Educational research glossary" in capsys.readouterr().out
    assert main(["terms", "show", "unknown-term"]) == 1
    assert "Unknown VC term" in capsys.readouterr().err
    assert main(["investment-comparables", "--db", str(inputs["db"]), "--company", "Heart AI"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["individual_fund_check"]["amount"] is None
    assert main(["vc-documents", "--db", str(inputs["db"]), "--source-id", "syn-01"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unverified_link_catalog"
    assert main(["vc-fetch-document", "--db", str(inputs["db"]), "--source-id", "syn-01"]) == 1
    assert "explicit --online" in capsys.readouterr().err
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(dict(name="SYNTHETIC NEW", intended_use="Cardiac ultrasound triage", clinical_indication="Cardiac", input_modality="Ultrasound")))
    assert main(["investment-comparables", "--db", str(inputs["db"]), "--profile", str(profile), "--fda-db", str(tmp_path / "no-fda.sqlite")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["profile_comparison"]["profile_review_status"] == "pending_review"
    assert len(result["results"]) == 1
    proc = subprocess.run([sys.executable, "-S", "-m", "vc_engine", "vc-documents", "--db", str(inputs["db"])], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_pagination_and_readonly_investments(inputs):
    before = inputs["db"].read_bytes()
    report = query_investments(db=inputs["db"], filters=InvestmentFilters(limit=1, offset=1))
    assert report.total_matching == 2 and len(report.results) == 1
    assert before == inputs["db"].read_bytes()


def test_blank_catalog_query_and_blank_download_id(inputs, tmp_path):
    assert len(query_catalog(db=inputs["db"], keyword="   ")) == 1
    session = Session()
    with pytest.raises(ValueError, match="must not be blank"):
        fetch_document("   ", db=inputs["db"], output_dir=tmp_path / "none", online=True, session=session)
    assert not session.calls and not (tmp_path / "none").exists()


def test_formula_share_count_and_percentage_units_not_interchangeable():
    payload = valid_registry()
    payload["terms"][0]["formula"] = dict(expression="shares + percentage", variables={"shares": "shares", "percentage": "percentage"}, caveats=["Synthetic invalid formula"])
    with pytest.raises(ValueError, match="incompatible units"):
        validate_registry(payload)


def test_unquoted_yaml_review_date_and_published_schema_agree(tmp_path):
    import yaml
    payload = valid_registry()
    payload["terms"][0].update(status="reviewed", reviewed_by="Synthetic Reviewer", review_note="Synthetic review", reviewed_on="2026-10-21")
    text = yaml.safe_dump(payload).replace("'2026-10-21'", "2026-10-21")
    path = tmp_path / "reviewed.yaml"
    path.write_text(text, encoding="utf-8")
    assert load_terms(path)[0].reviewed_on == "2026-10-21"
    schema = json.loads(DEFAULT_TERMS.with_name("vc_terms.schema.json").read_text())
    assert schema["$defs"]["term"]["required"]
    assert all(term.unit in schema["$defs"]["unit"]["enum"] for term in load_terms())
