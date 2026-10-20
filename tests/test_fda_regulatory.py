"""Mock-only FDA fixtures: identifiers/text below are synthetic, not evidence."""
import json
import socket
import sqlite3
import subprocess
import sys
from dataclasses import asdict

import pytest
import requests

from vc_engine.__main__ import main
from vc_engine.database import connect
from vc_engine.fda_client import FDAError
from vc_engine.regulatory_models import FDA_ENDPOINT, FDAQuery, FetchLimits
from vc_engine.regulatory_search import search_precedents
from vc_engine.regulatory_store import FDAStore


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *items):
        self.items, self.calls = list(items), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert url == FDA_ENDPOINT
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"][0] > 0
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("FDA unit tests must never use real network")
    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(requests.Session, "get", unexpected)


def raw(identifier="K000001", **updates):
    return dict(k_number=identifier, device_name="Synthetic echocardiography analysis",
        applicant="Synthetic Manufacturer", decision_date="20260102", decision_code="SESE",
        decision_description="SYNTHETIC DECISION TEXT", product_code="ABC",
        openfda={"medical_specialty_description": ["Synthetic specialty"]}, **updates)


def page(*rows, total=None):
    return Response(dict(results=list(rows), meta={"results": {"total": len(rows) if total is None else total}}))


def online(tmp_path, session, **kwargs):
    return search_precedents(FDAQuery(query="echocardiography"), db=tmp_path / "fda.sqlite", online=True,
                              session=session, sleeper=lambda seconds: None, **kwargs)


def test_live_persistence_and_offline_status(tmp_path):
    session = Session(page(raw()))
    first = online(tmp_path, session)
    record = first.results[0]
    assert record.k_number == "K000001" and record.decision_date == "2026-01-02"
    assert record.decision_description == "SYNTHETIC DECISION TEXT"
    assert record.verified_by_official_record is True
    assert record.evidence_status == "live_official_record"
    assert record.source_checked_at == record.fetched_at
    assert record.evidence_urls == (record.source_url,)
    assert first.checked_official_urls == (record.source_url,)
    assert "not FDA approval" in " ".join(first.warnings)
    cached = search_precedents(first.query, db=tmp_path / "fda.sqlite")
    assert cached.evidence_status == "cached" and cached.checked_official_urls == ()
    assert cached.results[0].verified_by_official_record is False
    assert cached.results[0].source_checked_at == record.source_checked_at
    assert cached.results[0].retrieval_status == "cached"
    assert cached.requests_made == 0
    with FDAStore(tmp_path / "fda.sqlite", readonly=True) as store:
        assert len(store.records()) == 1
        assert json.loads(store.records()[0]["raw_json"]) == raw()
        assert store.connection.execute("SELECT COUNT(*) FROM fda_pages").fetchone()[0] == 1


def test_fresh_cache_online_does_not_claim_live_and_refresh_upserts(tmp_path):
    first = online(tmp_path, Session(page(raw())))
    second_session = Session()
    second = online(tmp_path, second_session)
    assert second_session.calls == []
    assert second.evidence_status == "cached" and second.results[0].verified_by_official_record is False
    refreshed = online(tmp_path, Session(page(raw())), refresh=True)
    assert refreshed.evidence_status == "live_official_record"
    with FDAStore(tmp_path / "fda.sqlite", readonly=True) as store:
        assert len(store.records()) == 1
        assert store.connection.execute("SELECT COUNT(*) FROM fda_pages").fetchone()[0] == 1
    assert first.results[0].k_number == refreshed.results[0].k_number


@pytest.mark.parametrize("response", [page(), Response({"error": {"code": "NOT_FOUND", "message": "No matches found!"}}, 404)])
def test_no_results_are_cached(tmp_path, response):
    first = online(tmp_path, Session(response))
    assert first.results == () and first.evidence_status == "live_no_results"
    second = online(tmp_path, Session())
    assert second.results == () and second.evidence_status == "cached_no_results"


def test_repeated_pages_stop_and_duplicate_ids_deduplicate(tmp_path):
    rows = [raw("K000001"), raw("K000002")]
    result = online(tmp_path, Session(page(*rows, total=9), page(*rows, total=9)),
                    limit=6, limits=FetchLimits(page_size=2))
    assert len(result.results) == 2 and result.pages_read == 2 and result.truncated
    assert "Repeated FDA page" in " ".join(result.limitations)
    result = online(tmp_path, Session(page(raw("K000001"), raw("K000003"), total=4),
                                     page(raw("K000003"), raw("K000004"), total=4)),
                    limit=4, limits=FetchLimits(page_size=2), refresh=True)
    assert {r.k_number for r in result.results} == {"K000001", "K000003", "K000004"}
    assert result.records_seen == 4


def test_caps_and_unknown_total_are_explicit(tmp_path):
    result = online(tmp_path, Session(page(raw(), total=999)), limit=50,
                    limits=FetchLimits(page_size=1, max_pages=1, max_records=1))
    assert result.truncated and result.requests_made == 1
    assert len(result.results) == 1
    assert "not exhaustive" in " ".join(result.limitations)


def test_missing_fields_and_invalid_ids_are_never_invented(tmp_path):
    payload = [{"k_number": "K000001"}, {}, {"k_number": "MADE_UP"}]
    result = online(tmp_path, Session(page(*payload)), limit=3)
    assert len(result.results) == 1
    record = result.results[0]
    assert record.device_name is None and record.applicant is None and record.decision_date is None
    assert "unknown/unparseable" in " ".join(record.limitations)
    assert "no identifiers synthesized" in " ".join(result.limitations)


def test_exact_filters_and_query_syntax_are_not_interpreted_as_instructions(tmp_path):
    query = FDAQuery(device_name="Synthetic echocardiography analysis", applicant="Synthetic Manufacturer", product_code="ABC")
    session = Session(page(raw()))
    result = search_precedents(query, db=tmp_path / "fda.sqlite", online=True, session=session, sleeper=lambda _: None)
    expression = session.calls[0][1]["params"]["search"]
    assert 'applicant.exact:"Synthetic Manufacturer"' in expression
    assert 'product_code:"ABC"' in expression
    assert 'product_code.exact' not in expression
    assert len(result.results) == 1
    assert len(result.results[0].relevance_reasons) == 3
    assert '\\"' in FDAQuery(query='x" OR k_number:*').expression()
    rejected = search_precedents(FDAQuery(k_number="K000002"), db=tmp_path / "fda.sqlite", online=True,
        session=Session(page(raw())), sleeper=lambda _: None)
    assert not rejected.results
    assert "did not match" in " ".join(rejected.limitations)


def test_exact_k_import_reuses_offline_records_and_cli(tmp_path, capsys):
    online(tmp_path, Session(page(raw())))
    assert main(["fda-import", "--k-number", "K000001", "--fda-db", str(tmp_path / "fda.sqlite")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["evidence_status"] == "cached"
    assert output["results"][0]["verified_by_official_record"] is False
    assert main(["fda-search", "--query", "echocardiography", "--fda-db", str(tmp_path / "fda.sqlite")]) == 0
    assert main(["fda-search", "--query", "echocardiography", "--refresh"]) == 1
    assert "requires --online" in capsys.readouterr().err


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 429])
def test_http_errors_include_api_message_and_preserve_existing_cache(tmp_path, status):
    online(tmp_path, Session(page(raw())))
    response = Response({"error": {"code": "ERROR", "message": "Synthetic API message"}}, status)
    with pytest.raises(FDAError, match=f"HTTP {status}: Synthetic API message"):
        online(tmp_path, Session(response), refresh=True, limits=FetchLimits(retries=0))
    assert search_precedents(FDAQuery(query="echocardiography"), db=tmp_path / "fda.sqlite").results


def test_retry_backoff_and_timeout(tmp_path):
    waits = []
    session = Session(Response({"error": {"message": "Busy"}}, 503, {"Retry-After": "1"}), page(raw()))
    result = search_precedents(FDAQuery(query="echo"), db=tmp_path / "fda.sqlite", online=True,
        session=session, sleeper=waits.append)
    assert result.requests_made == 2 and 1 in waits
    timeout = Session(requests.Timeout(), requests.Timeout(), requests.Timeout())
    with pytest.raises(FDAError, match="timeout/connection"):
        online(tmp_path, timeout, refresh=True)
    assert len(timeout.calls) == 3
    with pytest.raises(FDAError, match="bounded wait"):
        online(tmp_path, Session(Response({}, 429, {"Retry-After": "120"})), refresh=True)


@pytest.mark.parametrize("response", [Response(b"not-json"), Response({"results": {}}),
    Response({"results": [], "error": {"message": "error"}}), Response(b"x" * (4 * 1024 * 1024 + 1))])
def test_invalid_and_oversized_responses_fail_without_records(tmp_path, response):
    with pytest.raises(FDAError):
        online(tmp_path, Session(response))
    assert response.closed
    with FDAStore(tmp_path / "fda.sqlite", readonly=True) as store:
        assert not store.records()


def test_stale_offline_cache_does_not_request_network(tmp_path):
    online(tmp_path, Session(page(raw())))
    with FDAStore(tmp_path / "fda.sqlite") as store:
        with store.connection:
            store.connection.execute("UPDATE fda_records SET fetched_at='2000-01-01T00:00:00+00:00'")
    result = search_precedents(FDAQuery(query="echocardiography"), db=tmp_path / "fda.sqlite")
    assert result.results[0].verified_by_official_record is False
    assert "older than" in " ".join(result.results[0].limitations)


def test_stale_online_page_refreshes_and_connection_error_can_retry(tmp_path):
    online(tmp_path, Session(page(raw())))
    with FDAStore(tmp_path / "fda.sqlite") as store:
        with store.connection:
            store.connection.execute("UPDATE fda_pages SET fetched_at='2000-01-01T00:00:00+00:00'")
    session = Session(requests.ConnectionError(), page(raw()))
    result = online(tmp_path, session)
    assert result.evidence_status == "live_official_record" and result.requests_made == 2


def test_overfull_page_rejected_and_cached_exact_filters_are_local(tmp_path):
    with pytest.raises(FDAError, match="results length"):
        online(tmp_path, Session(page(raw("K000001"), raw("K000002"))), limit=1)
    online(tmp_path, Session(page(raw())))
    result = search_precedents(FDAQuery(applicant="Synthetic Manufacturer", product_code="abc"), db=tmp_path / "fda.sqlite")
    assert len(result.results) == 1 and result.requests_made == 0
    assert 'product_code:"ABC"' in FDAQuery(product_code="abc").expression()
    assert not search_precedents(FDAQuery(applicant="Different Manufacturer"), db=tmp_path / "fda.sqlite").results


def test_absent_cache_offline_and_stdlib_only_cli(tmp_path):
    path = tmp_path / "absent.sqlite"
    result = search_precedents(FDAQuery(query="echo"), db=path)
    assert result.evidence_status == "cache_miss" and not path.exists()
    proc = subprocess.run([sys.executable, "-S", "-m", "vc_engine", "fda-search", "--query", "echo", "--fda-db", str(path)],
        text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["evidence_status"] == "cache_miss"


def test_database_isolation_and_no_implicit_migration(tmp_path):
    path = tmp_path / "vc.sqlite"
    with connect(path) as conn:
        conn.execute("INSERT INTO companies (id,name,name_key,raw_json) VALUES ('test','Test','test','{}')")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="separate --fda-db"):
        search_precedents(FDAQuery(query="echo"), db=path, online=True, session=Session())
    assert path.read_bytes() == original
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1


@pytest.mark.parametrize("query", [FDAQuery(), FDAQuery(k_number="Kfake"), FDAQuery(product_code="ABC*"), FDAQuery(query="a"*301)])
def test_invalid_query_does_not_create_cache(tmp_path, query):
    with pytest.raises(ValueError):
        search_precedents(query, db=tmp_path / "no.sqlite", online=True, session=Session())
    assert not (tmp_path / "no.sqlite").exists()


@pytest.mark.parametrize("limits", [FetchLimits(page_size=0), FetchLimits(max_pages=26), FetchLimits(retries=4),
                                    FetchLimits(timeout=float("nan")), FetchLimits(cache_hours=-1)])
def test_invalid_limits_fail_before_network(tmp_path, limits):
    with pytest.raises(ValueError):
        online(tmp_path, Session(), limits=limits)
