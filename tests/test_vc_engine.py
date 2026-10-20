"""Synthetic CSVs only; no network, models or real investment evidence."""
import csv
import json
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from vc_engine.__main__ import main
from vc_engine.database import connect
from vc_engine.ingest import ImportValidationError, ingest, money
from vc_engine.models import HEADERS, QueryFilters, iso_date, number, year
from vc_engine.queries import provenance, search_companies, search_documents, stats


def write_csv(path, kind, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS[kind])
        writer.writeheader()
        for values in rows:
            writer.writerow({field: values.get(field, "") for field in HEADERS[kind]})


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("VC must never use the network")
    monkeypatch.setattr(socket, "create_connection", no_network)
    companies, investments, documents = (tmp_path / name for name in ("companies.csv", "investments.csv", "documents.csv"))
    write_csv(companies, "companies", [dict(company="  Heart   AI ", headquarters_country="Germany",
        clinical_category="Cardiology", clinical_use_case="Rhythm monitoring",
        dealroom_reported_total_funding_usd_millions="12.5", research_date="2026-10-17",
        regulatory_status_as_reported="CSV says verified", risk_flags="Synthetic only\nNo evidence")])
    write_csv(investments, "investments", [
        dict(investor="Fund A", company="heart ai", round_stage="Seed", round_date="2025-01-02",
             reported_round_amount="10,000,000", reported_round_currency="EUR",
             verification_level="Verified according to CSV", individual_fund_check_amount="USD 500,000"),
        dict(investor="Fund B", company="Heart AI", round_stage="Series A", round_date="2026-02-03"),
        dict(investor="Fund A", company="Heart AI", round_stage="Series A", round_date="2026-02-03"),
    ])
    write_csv(documents, "source_documents", [dict(source_id="SYN-01", fund_name="Fund A",
        document_title="Synthetic cardiology thesis", verification_status="Verified in input",
        direct_document_or_page_url="https://example.invalid/thesis", observed_2026_10_16="2026-10-16")])
    return dict(companies=companies, investments=investments, documents=documents,
                db=tmp_path / "vc.sqlite", report_path=tmp_path / "quality.json")


def test_reimport_counts_amounts_provenance_and_quality(inputs):
    first = ingest(**inputs)
    assert [s["rows_read"] for s in first["files"].values()] == [1, 3, 1]
    assert all(s["rows_rejected"] == 0 for s in first["files"].values())
    with connect(inputs["db"], readonly=True) as conn:
        before = stats(conn)
        result = search_companies(conn, QueryFilters(keyword="CARDIOLOGY"))[0]
        assert result.total_funding_amount == 12_500_000
        assert result.total_funding_currency == "USD"
        assert result.revenue_amount is None and result.revenue_currency is None
        assert len(result.investments) == 3
        seed = next(row for row in result.investments if row["stage"] == "Seed")
        assert (seed["round_amount"], seed["round_currency"]) == (10_000_000, "EUR")
        assert (seed["fund_check_amount"], seed["fund_check_currency"]) == (500_000, "USD")
        assert all(row["round_amount"] is None for row in result.investments if row["stage"] != "Seed")
        claims = provenance(conn, "companies", result.id)
        assert any(row["raw_value"] == "  Heart   AI " and row["row_number"] == 2 for row in claims)
        assert any(row["field_name"] == "revenue_value" and row["raw_value"] == "" for row in claims)
        assert any(row["end_line_number"] > row["row_number"] for row in claims)
        assert all(row["independently_verified"] == 0 for row in claims)
        assert before["data_quality"] == dict(unknown_clinical_study_url=1, unknown_revenue=1,
            unverified_regulatory_status=1, missing_investment_round_amount=2)
    second = ingest(**inputs)
    assert second["summary"] == before
    assert all(changes["inserted"] == 0 for changes in second["entity_changes"].values())
    assert second["entity_changes"]["investments"]["unchanged"] == 3
    assert json.loads(inputs["report_path"].read_text(encoding="utf-8")) == second


def test_filters_documents_pagination_and_sql_literals(inputs):
    ingest(**inputs)
    with connect(inputs["db"], readonly=True) as conn:
        for field, value in (("country", "germany"), ("clinical_category", "cardiology"),
                             ("company", "Heart AI"), ("investor", "Fund A"), ("stage", "Seed")):
            assert len(search_companies(conn, QueryFilters(**{field: value}))) == 1
        assert not search_companies(conn, QueryFilters(investor="Fund B", stage="Seed"))
        assert not search_companies(conn, QueryFilters(keyword="%' OR 1=1 --"))
        assert not search_companies(conn, QueryFilters(offset=1))
        assert search_documents(conn, keyword="cardiology", fund_name="fund a")[0].source_id == "syn-01"
        assert not search_documents(conn, keyword="%")
        with pytest.raises(ValueError, match="limit"):
            search_companies(conn, QueryFilters(limit=0))


def test_changed_values_update_entity_and_preserve_source_history(inputs):
    ingest(**inputs)
    write_csv(inputs["companies"], "companies", [dict(company="Heart AI", revenue_value="EUR 42", founded_year="circa 2020")])
    report = ingest(**inputs)
    assert report["entity_changes"]["companies"]["updated"] == 1
    assert report["files"]["companies"]["normalization_issues"][0]["fields"] == ["founded_year"]
    with connect(inputs["db"], readonly=True) as conn:
        company = search_companies(conn)[0]
        assert company.revenue_amount == 42 and company.revenue_currency == "EUR"
        claims = [c for c in provenance(conn, "companies", company.id) if c["field_name"] == "revenue_value"]
        assert {c["raw_value"] for c in claims} == {"", "EUR 42"}
        assert len({c["file_sha256"] for c in claims}) == 2


@pytest.mark.parametrize("header", ["company", ",".join(HEADERS["companies"]) + ",surprise",
                                    ",".join(HEADERS["companies"]) + ",company"])
def test_invalid_headers_fail_before_any_database_mutation(inputs, header):
    inputs["companies"].write_text(header + "\n", encoding="utf-8")
    with pytest.raises(ImportValidationError, match="invalid CSV columns"):
        ingest(**inputs)
    assert not inputs["db"].exists()
    assert json.loads(inputs["report_path"].read_text())["status"] == "failed_preflight"


def test_bad_rows_rejected_and_placeholder_company_created(inputs):
    write_csv(inputs["investments"], "investments", [dict(company="Orphan", investor="Fund C"), dict(company="No investor")])
    with inputs["companies"].open("a", encoding="utf-8", newline="") as stream:
        stream.write("bad,width\n")
    report = ingest(**inputs)
    assert report["files"]["companies"]["rows_read"] == 2
    assert report["files"]["companies"]["rows_rejected"] == 1
    assert report["files"]["investments"]["rows_rejected"] == 1
    assert report["status"] == "completed_with_rejections"
    with connect(inputs["db"], readonly=True) as conn:
        assert len(search_companies(conn)) == 2
        orphan = search_companies(conn, QueryFilters(company="Orphan"))[0]
        assert provenance(conn, "companies", orphan.id)[0]["input_filename"] == "investments.csv"


@pytest.mark.parametrize("raw,expected", [("", None), ("0", 0), ("1,234.5", 1234.5),
    ("1,2", None), ("10-20", None), ("NaN", None), ("1e10", None), ("EUR 3", None)])
def test_conservative_numbers(raw, expected):
    assert number(raw) == expected


def test_currency_dates_and_years():
    assert money("12") == (None, None)
    assert money("12", "eur") == (12, "EUR")
    assert money("USD 12", "EUR") == (None, "EUR")
    assert money("$12") == (None, None)
    assert money("EUR 12 million") == (None, None)
    assert iso_date("2026-02-30") is None
    assert iso_date("2026-02") is None
    assert year("2020.0") is None


def test_cli_and_no_mdr_dependencies(inputs, capsys):
    args = ["ingest"]
    for key, value in inputs.items():
        args.extend(["--report" if key == "report_path" else "--" + key, str(value)])
    assert main(args) == 0
    assert main(["stats", "--db", str(inputs["db"])]) == 0
    assert main(["search", "--query", "cardiology", "--db", str(inputs["db"])]) == 0
    assert main(["search", "--entity", "documents", "--query", "thesis", "--db", str(inputs["db"])]) == 0
    assert "Heart AI" in capsys.readouterr().out
    # -S omits site-packages, proving CLI import uses only the standard library.
    completed = subprocess.run([sys.executable, "-S", "-m", "vc_engine", "stats", "--db", str(inputs["db"])],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["counts"]["investments"] == 3


def test_missing_inputs_and_readonly_commands_do_not_create_db(inputs, capsys):
    inputs["companies"].unlink()
    with pytest.raises(ImportValidationError):
        ingest(**inputs)
    assert not inputs["db"].exists()
    assert main(["stats", "--db", str(inputs["db"])]) == 1
    assert not inputs["db"].exists()
    assert "ERROR" in capsys.readouterr().err


def test_reject_other_databases_and_output_collisions(inputs):
    with sqlite3.connect(inputs["db"]) as conn:
        conn.execute("CREATE TABLE mdr_sentinel (value TEXT)")
    with pytest.raises(ValueError, match="separate VC DB"):
        ingest(**inputs)
    assert json.loads(inputs["report_path"].read_text())["status"] == "failed_database"
    with sqlite3.connect(inputs["db"]) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("mdr_sentinel",)]
    with pytest.raises(ValueError, match="Report path"):
        ingest(**{**inputs, "report_path": inputs["companies"]})


def test_blank_lines_and_multiline_fields_have_exact_physical_provenance(inputs):
    text = inputs["companies"].read_text(encoding="utf-8-sig")
    header, rest = text.split("\n", 1)
    inputs["companies"].write_text(header + "\n\n\n" + rest, encoding="utf-8")
    ingest(**inputs)
    with connect(inputs["db"], readonly=True) as conn:
        claim = conn.execute("SELECT row_number,end_line_number FROM source_rows WHERE dataset='companies'").fetchone()
        assert tuple(claim) == (4, 5)


def test_input_counts_precede_deduplication(inputs):
    # Synthetic counts exercise the required report sizes, not the absent real CSVs.
    write_csv(inputs["companies"], "companies", [dict(company="Repeated company")] * 50)
    write_csv(inputs["investments"], "investments", [dict(company="Repeated company", investor="Repeated fund")] * 50)
    write_csv(inputs["documents"], "source_documents", [dict(source_id=f"SYN-{n}", document_title=f"Synthetic {n}") for n in range(66)])
    report = ingest(**inputs)
    assert [row["rows_read"] for row in report["files"].values()] == [50, 50, 66]
    assert report["summary"]["counts"]["companies"] == 1
    assert report["summary"]["counts"]["investments"] == 1
    assert report["summary"]["counts"]["source_documents"] == 66
    assert report["entity_changes"]["investments"] == dict(inserted=1, updated=0, unchanged=49)
    repeated = ingest(**inputs)
    assert repeated["summary"] == report["summary"]


def test_database_failure_rolls_back_all_files_and_saves_report(inputs):
    with connect(inputs["db"]) as conn:
        conn.execute("CREATE TRIGGER fail_investment BEFORE INSERT ON investments "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
        ingest(**inputs)
    with connect(inputs["db"], readonly=True) as conn:
        assert all(count == 0 for count in stats(conn)["counts"].values())
    report = json.loads(inputs["report_path"].read_text())
    assert report["status"] == "failed_transaction"
    assert all(row["rows_imported"] == 0 for row in report["files"].values())
