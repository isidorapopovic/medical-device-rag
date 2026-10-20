"""Unverified link catalog plus a separate, explicit bounded download operation."""
import hashlib
import ipaddress
import json
import socket
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from .database import connect
from .ingest import write_report
from .models import DEFAULT_DB, ROOT, clean
from .regulatory_models import utc_now

DEFAULT_DOWNLOADS = ROOT / "data/vc/downloads"


@dataclass(frozen=True)
class CatalogEntry:
    record_id: str
    source_id: str
    fund_name: str | None
    title: str
    source_url: str | None
    landing_page: str | None
    expected_extractable_fields: str | None
    verification_status_as_reported: str | None
    research_priority: str | None
    observed_date_as_reported: str | None
    document_type: str | None
    format_as_reported: str | None
    notes: str | None
    field_provenance: tuple[dict, ...]
    evidence_status: str = "unverified_link_catalog"
    content_status: str = "Catalog entry only; this query does not fetch or inspect document content"


def catalog(connection, *, keyword: str | None = None, fund: str | None = None,
            priority: str | None = None, source_id: str | None = None, limit: int = 100, offset: int = 0) -> list[CatalogEntry]:
    from .queries import provenance
    if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
        raise ValueError("Catalog limit must be 1–1000 and offset nonnegative")
    keyword, fund, priority, source_id = (clean(value) for value in (keyword, fund, priority, source_id))
    result = []
    for row in connection.execute("SELECT * FROM source_documents ORDER BY source_id"):
        raw = json.loads(row["raw_json"])
        if source_id and (clean(raw.get("source_id")) or "").casefold() != (clean(source_id) or "").casefold():
            continue
        if fund and (clean(raw.get("fund_name")) or "").casefold() != (clean(fund) or "").casefold():
            continue
        if priority and (clean(raw.get("research_priority")) or "").casefold() != (clean(priority) or "").casefold():
            continue
        if keyword and clean(keyword).casefold() not in " ".join(str(value or "") for value in raw.values()).casefold():
            continue
        origins = tuple(dict(source_id=claim["source_row_id"], field=claim["field_name"], quote=claim["raw_value"],
            input_filename=claim["input_filename"], row_number=claim["row_number"], file_sha256=claim["file_sha256"])
            for claim in provenance(connection, "source_documents", row["id"]))
        result.append(CatalogEntry(row["id"], raw["source_id"], clean(raw.get("fund_name")), row["title"], row["url"], row["landing_page"],
            clean(raw.get("expected_extractable_fields")), row["verification_as_reported"], clean(raw.get("research_priority")),
            clean(raw.get("observed_2026_10_16")), row["document_type"], clean(raw.get("format")), clean(raw.get("important_notes")), origins))
    return result[offset:offset + limit]


def query_catalog(*, db: str | Path = DEFAULT_DB, **kwargs) -> list[CatalogEntry]:
    with closing(connect(db, readonly=True)) as connection:
        return catalog(connection, **kwargs)


def public_https_url(url: str, *, resolver=socket.getaddrinfo) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("Downloads require a public HTTPS URL without credentials/nonstandard ports")
    addresses = resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Download host must resolve only to public Internet addresses")


def fetch_document(source_id: str, *, db: str | Path = DEFAULT_DB, output_dir: str | Path = DEFAULT_DOWNLOADS,
                   online: bool = False, extract: bool = False, timeout: float = 15,
                   max_bytes: int = 20 * 1024 * 1024, session=None, resolver=socket.getaddrinfo) -> dict:
    """Download bytes/text only; never extract financial facts or change source claims."""
    if not online:
        raise ValueError("Document fetching requires explicit --online; catalog queries are offline")
    if not isinstance(source_id, str) or not clean(source_id):
        raise ValueError("Document source_id must not be blank")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 20 * 1024 * 1024 or not 0.1 <= timeout <= 60:
        raise ValueError("max_bytes must be 1–20971520 and timeout 0.1–60 seconds")
    entries = query_catalog(db=db, source_id=source_id, limit=1)
    if not entries:
        raise ValueError("Unknown document catalog source_id: " + source_id)
    entry = entries[0]
    output_dir = Path(output_dir).resolve()
    attempt_id = uuid4().hex
    manifest_path = output_dir / "attempts" / (attempt_id + ".json")
    attempt = dict(attempt_id=attempt_id, source_id=entry.source_id, catalog_record_id=entry.record_id,
        attempted_at=utc_now(), observed_at=None, catalog_observed_date=entry.observed_date_as_reported,
        url=entry.source_url, final_url=None, http_status=None, checksum_sha256=None, byte_size=0,
        content_path=None, download_status="started", extraction_status="not_attempted", extraction_errors=[],
        request_log=[], errors=[], evidence_status="download_not_financial_verification",
        limitations=["A downloaded file or extracted passage does not establish financial facts, investment participation or regulatory status.",
                     "No NAV, fund returns, valuations or investor checks are generated; source review is still required."])
    write_report(manifest_path, attempt)
    owns_session = session is None
    try:
        if not entry.source_url:
            raise ValueError("Catalog source URL is unknown")
        import requests
        if session is None:
            session = requests.Session()
        url, payload, content_type = entry.source_url, None, ""
        for hop in range(4):
            public_https_url(url, resolver=resolver)
            started = time.monotonic()
            response = None
            try:
                response = session.get(url, timeout=(min(5, timeout), timeout), stream=True,
                    allow_redirects=False, headers={"User-Agent": "medical-device-rag-vc/0.4 (public research documents)"})
                attempt["http_status"] = response.status_code
                attempt["final_url"] = url
                attempt["request_log"].append(dict(url=url, http_status=response.status_code, observed_at=utc_now()))
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location or hop == 3:
                        raise ValueError("Missing redirect location or redirect cap reached")
                    url = urljoin(url, location)
                    continue
                if response.status_code != 200:
                    raise ValueError(f"Document HTTP {response.status_code}")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > max_bytes or time.monotonic() - started > timeout:
                        raise ValueError("Document byte/time cap exceeded")
                    chunks.append(chunk)
                payload = b"".join(chunks)
                content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
                break
            finally:
                if response is not None:
                    response.close()
        if not payload:
            raise ValueError("Empty document response")
        checksum = hashlib.sha256(payload).hexdigest()
        suffix = ".pdf" if payload.startswith(b"%PDF-") else ".docx" if payload.startswith(b"PK") and content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" else ".txt" if content_type == "text/plain" else ".html" if content_type == "text/html" else ".bin"
        blob = output_dir / "files" / (checksum + suffix)
        blob.parent.mkdir(parents=True, exist_ok=True)
        if blob.exists():
            if hashlib.sha256(blob.read_bytes()).hexdigest() != checksum:
                raise ValueError("Existing checksum-addressed file does not match its name")
        else:
            with blob.open("xb") as stream:
                stream.write(payload)
        attempt.update(checksum_sha256=checksum, byte_size=len(payload), content_path=str(blob),
                       content_type=content_type, download_status="downloaded")
        if extract:
            try:
                if suffix not in {".pdf", ".docx", ".txt"}:
                    raise ValueError("No supported PDF/DOCX/TXT content detected; HTML pages are not treated as reports")
                from mdr_rag.document_parsers import parse_document
                extraction = parse_document(payload, suffix, ocr_enabled=False)
                extracted = output_dir / "extractions" / (checksum + ".json")
                write_report(extracted, extraction.model_dump(mode="json"))
                attempt.update(extraction_status=extraction.status, extraction_path=str(extracted),
                    extraction_errors=list(extraction.diagnostics),
                    extraction_flags=sorted({flag for unit in extraction.units for flag in unit.flags}))
            except Exception as exc:
                attempt.update(extraction_status="failed", extraction_errors=[str(exc)[:300]])
    except Exception as exc:
        attempt["download_status"] = "failed"
        attempt["errors"].append((str(exc) or type(exc).__name__)[:300])
    finally:
        if owns_session and session is not None:
            session.close()
        attempt["observed_at"] = utc_now()
        write_report(manifest_path, attempt)
    return {**attempt, "manifest_path": str(manifest_path)}
