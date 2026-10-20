"""Deterministic research matches; never selects a predicate or infers clearance."""
import json
from datetime import datetime, timezone
from pathlib import Path

from .database import json_text
from .fda_client import FDAClient, FDAPage
from .models import clean, iso_date
from .regulatory_models import (DEFAULT_FDA_DB, FDAQuery, FetchLimits, RegulatoryPrecedent,
                                RegulatorySearchResult, WARNINGS, k_number)
from .regulatory_store import FDAStore


def _text(raw: dict, key: str) -> str | None:
    return clean(raw.get(key)) if isinstance(raw.get(key), str) else None


def normalize(raw: dict, page: FDAPage) -> dict | None:
    identifier = _text(raw, "k_number")
    try:
        identifier = k_number(identifier or "")
    except ValueError:
        return None
    date = _text(raw, "decision_date")
    if date and len(date) == 8 and date.isdigit():
        date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    harmonized = raw.get("openfda")
    specialty = harmonized.get("medical_specialty_description") if isinstance(harmonized, dict) else None
    if isinstance(specialty, list):
        specialty = "; ".join(item for item in specialty if isinstance(item, str)) or None
    if not isinstance(specialty, str):
        specialty = None
    return dict(k_number=identifier, device_name=_text(raw, "device_name"), applicant=_text(raw, "applicant"),
                decision_date=iso_date(date), decision_code=_text(raw, "decision_code"),
                decision_description=_text(raw, "decision_description"), product_code=_text(raw, "product_code"),
                medical_specialty=clean(specialty), raw_json=json_text(raw), source_url=page.source_url,
                fetched_at=page.fetched_at, checked_at=page.fetched_at, retrieval_status="fetched_official")


def precedent(record: dict, query: FDAQuery, *, live: bool = False, stale: bool = False) -> RegulatoryPrecedent:
    raw = json.loads(record["raw_json"])
    reasons = []
    if clean(query.query):
        reasons.append(f"Device-name text search for {clean(query.query)!r}; no semantic or intended-use equivalence inferred.")
    for field in ("device_name", "applicant", "product_code", "k_number"):
        if clean(getattr(query, field)):
            reasons.append(f"Exact {field} match: {clean(getattr(query, field))}.")
    limitations = list(WARNINGS)
    missing = [field for field in ("device_name", "applicant", "decision_date", "decision_description", "product_code", "medical_specialty") if record[field] is None]
    if missing:
        limitations.append("Official record fields unknown/unparseable: " + ", ".join(missing) + ".")
    if not live:
        limitations.append("Cached snapshot only; official source was not checked during this invocation.")
    if stale:
        limitations.append("Snapshot is older than the configured cache lifetime or its timestamp is invalid.")
    limitations.append("No decision-summary PDF or indications-for-use document was retrieved or compared.")
    return RegulatoryPrecedent(**{field: record[field] for field in (
        "k_number", "device_name", "applicant", "decision_date", "decision_code", "decision_description",
        "product_code", "medical_specialty", "source_url", "fetched_at")},
        source_checked_at=record["checked_at"], retrieval_status="fetched_official" if live else "cached",
        evidence_status="live_official_record" if live else "cached",
        verified_by_official_record=live, relevance_reasons=tuple(reasons), limitations=tuple(limitations),
        evidence_urls=(record["source_url"],), raw_fda_response=raw)


def _offline(store: FDAStore, query: FDAQuery, limit: int, limits: FetchLimits) -> RegulatorySearchResult:
    candidates = []
    for record in store.records(identifier=query.k_number):
        raw = json.loads(record["raw_json"])
        if not query.matches(raw):
            continue
        if clean(query.query) and clean(query.query).casefold() not in (record["device_name"] or "").casefold():
            continue
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(record["fetched_at"])).total_seconds()
        except (ValueError, TypeError):
            age = float("inf")
        candidates.append(precedent(record, query, stale=not 0 <= age <= limits.cache_hours * 3600))
    return RegulatorySearchResult(query=query, results=tuple(candidates[:limit]), evidence_status="cached" if candidates else "cache_miss",
        records_seen=len(candidates), total_reported=None, truncated=len(candidates) > limit,
        limitations=("Offline mode: only previously stored FDA records are searched; this is not an exhaustive FDA search.",
                     "Cached matching uses a literal device-name substring; live openFDA phrase matching may differ."))


def _live(client: FDAClient, query: FDAQuery, limit: int) -> RegulatorySearchResult:
    results, seen, signatures, notes = [], set(), set(), []
    pages, scanned, skip, total = 0, 0, 0, None
    truncated = False
    expression = query.expression()
    while pages < client.limits.max_pages and scanned < client.limits.max_records and len(results) < limit:
        size = min(client.limits.page_size, client.limits.max_records - scanned, limit - len(results))
        if skip > 25000:
            notes.append("openFDA skip cap reached.")
            truncated = True
            break
        page = client.page(expression, size=size, skip=skip)
        pages += 1
        payload = page.payload
        raw_rows = payload.get("results")
        if not isinstance(raw_rows, list) or len(raw_rows) > size:
            from .fda_client import FDAError
            raise FDAError("Invalid FDA page: unexpected results length/type")
        meta = payload.get("meta", {})
        reported = meta.get("results", {}).get("total") if isinstance(meta, dict) and isinstance(meta.get("results"), dict) else None
        total = reported if type(reported) is int and reported >= 0 else total
        signature = json_text(raw_rows)
        if signature in signatures:
            notes.append("Repeated FDA page detected; stopped pagination.")
            truncated = True
            break
        signatures.add(signature)
        records, invalid, mismatched = [], 0, 0
        for raw in raw_rows:
            scanned += 1
            record = normalize(raw, page) if isinstance(raw, dict) else None
            if record is None:
                invalid += 1
                continue
            if not query.matches(raw):
                mismatched += 1
                continue
            records.append(record)
            if record["k_number"] in seen:
                continue
            seen.add(record["k_number"])
            results.append(precedent(record, query, live=page.live, stale=page.stale))
        if invalid:
            notes.append(f"Skipped {invalid} record(s) with missing/invalid FDA k_number; no identifiers synthesized.")
        if mismatched:
            notes.append(f"Skipped {mismatched} record(s) that did not match supplied exact fields.")
        if page.live:
            client.store.save(dict(search=expression, limit=size, skip=skip, sort="decision_date:desc"),
                              payload, page.source_url, page.fetched_at, records)
            client.checked_urls.append(page.source_url)
        skip += len(raw_rows)
        if not raw_rows or (total is not None and skip >= total):
            break
        if len(raw_rows) < size:
            if total is not None and skip < total:
                truncated = True
                notes.append("Short FDA page before the reported total; completeness is unknown.")
            break
    else:
        truncated = total is None or skip < total
    if truncated:
        notes.append("Result/page/record cap or incomplete pagination; returned research matches are not exhaustive.")
    statuses = {result.evidence_status for result in results}
    if statuses:
        status = next(iter(statuses)) if len(statuses) == 1 else "mixed"
    else:
        status = ("live" if client.checked_urls else "cached") + ("_no_usable_records" if scanned else "_no_results")
    return RegulatorySearchResult(query=query, results=tuple(results), evidence_status=status,
        limitations=tuple(notes), checked_official_urls=tuple(client.checked_urls), pages_read=pages,
        requests_made=client.requests_made, records_seen=scanned, total_reported=total, truncated=truncated)


def search_precedents(query: FDAQuery, *, db: str | Path = DEFAULT_FDA_DB, limit: int = 10,
                      online: bool = False, refresh: bool = False, limits: FetchLimits = FetchLimits(),
                      session=None, sleeper=None) -> RegulatorySearchResult:
    """No network without online=True; query only includes explicitly supplied text."""
    query.expression()
    limits.validate()
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer from 1 to 1000")
    if refresh and not online:
        raise ValueError("--refresh requires --online")
    if not online and not Path(db).exists():
        return RegulatorySearchResult(query=query, results=(), evidence_status="cache_miss",
            limitations=("No local FDA cache exists. Network is disabled; use --online explicitly.",))
    with FDAStore(db, readonly=not online) as store:
        if not online:
            return _offline(store, query, min(limit, limits.max_records), limits)
        kwargs = dict(online=online, refresh=refresh, limits=limits, session=session)
        if sleeper is not None:
            kwargs["sleeper"] = sleeper
        with FDAClient(store, **kwargs) as client:
            return _live(client, query, limit)
