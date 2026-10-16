"""File loading, traceable chunking, source IDs, selection and citation checks."""
import hashlib
import re
from pathlib import Path
from typing import Any

import pymupdf as fitz
from docx import Document

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "documents"
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
DBDIR = ROOT / "vector_db"


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def norm(text: str) -> str:
    return " ".join(text.replace("\u00ad", "").replace("\u2010", "-").split()).casefold()


def is_real_quote(quote: str, source_text: str) -> bool:
    return len(norm(quote)) >= 12 and norm(quote) in norm(source_text)


def is_raw_quote(quote: str, source_text: str, start=None, end=None) -> bool:
    """Exact character-span check; repeated quotations require explicit offsets."""
    if not quote or (start is None) != (end is None):
        return False
    if start is not None:
        return (type(start) is int and type(end) is int and 0 <= start < end <= len(source_text)
                and source_text[start:end] == quote)
    first = source_text.find(quote)
    return first >= 0 and source_text.find(quote, first + 1) < 0


def parse_pages(spec: str, maximum: int | None = None) -> set[int]:
    """User-visible PDF page numbers (1 based)."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            left, right = int(a), int(b)
            if left < 1 or right < left:
                raise ValueError(f"Invalid page range: {part}")
            pages.update(range(left, right + 1))
        else:
            value = int(part)
            if value < 1:
                raise ValueError("Pages are 1-based")
            pages.add(value)
    if not pages:
        raise ValueError("Specify PDF page numbers such as 85-91 or 85,87-91")
    if maximum is not None and max(pages) > maximum:
        raise ValueError(f"Requested page exceeds PDF length: {maximum}")
    return pages


def chunks(text: str, size: int = 2000, overlap: int = 250):
    """Character chunks, respecting nearby paragraph/word boundaries when possible."""
    cleaned = re.sub(r"[ \t]+", " ", text.replace("\u00ad", ""))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        if end < len(cleaned):
            split = cleaned.rfind("\n", start + int(size * 0.65), end)
            if split == -1:
                split = cleaned.rfind(" ", start + int(size * 0.75), end)
            if split > start:
                end = split + 1
        part = cleaned[start:end].strip()
        if part:
            yield part
        if end >= len(cleaned):
            break
        start = max(start + 1, end - overlap)


def source_records(path: Path, kind: str) -> tuple[list[dict[str, Any]], list[str]]:
    from .ingestion import parse_records
    return parse_records(path, kind)


def make_record(source: str, sha: str, kind: str, page: int, order: int, text: str):
    identity = f"{source}|{sha}|{page}|{order}|{text}".encode("utf-8")
    return {
        "id": f"{kind[0].upper()}-{digest(identity)[:14]}",
        "text": text,
        "meta": {
            "source": source,
            "sha256": sha,
            "kind": kind,
            "page": page,
            "block": order,
        },
    }


def all_records() -> tuple[list[dict], list[str], list[dict]]:
    from .ingestion import IngestionStore, confined, extraction_warnings, records_from_manifest, safe_filename
    store = IngestionStore(STATE / "ingestion" if DOCS == ROOT / "documents" else DOCS / ".ingestion")
    all_chunks, warnings, manifest = [], [], []
    for kind in ("legal", "device"):
        folder = confined(DOCS, DOCS / kind)
        folder.mkdir(parents=True, exist_ok=True)
        names = [safe_filename(p.name).casefold() for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in {".pdf", ".docx", ".txt", ".md"}]
        if len(names) != len(set(names)):
            raise ValueError("Ambiguous source filenames after Unicode/Windows normalization")
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".pdf", ".docx", ".txt", ".md"}:
                continue
            ingested, manifest_hash = store.ingest_path(path, kind, allowed_root=DOCS)
            records, problems = records_from_manifest(ingested, manifest_hash), extraction_warnings(ingested)
            all_chunks.extend(records)
            warnings.extend(problems)
            manifest.append({
                "source": f"{kind}/{ingested.document.original_name}", "kind": kind,
                "sha256": ingested.document.sha256, "chunks": len(records),
                "document_id": str(ingested.document.id), "document_version": ingested.document.version,
                "manifest_sha256": manifest_hash, "parser_fingerprint": ingested.parser_fingerprint,
                "status": ingested.extraction.status,
            })
    return all_chunks, warnings, manifest


def resolve_source(source: str, documents_root: Path = DOCS, *, allow_missing: bool = False) -> Path:
    """Resolve logical normalized labels without renaming user-provided source files."""
    from .ingestion import confined, safe_filename
    kind, separator, name = source.partition("/")
    if kind not in {"legal", "device"} or not separator or "/" in name or "\\" in name:
        raise ValueError("Invalid source label")
    target = safe_filename(name).casefold()
    folder = confined(documents_root, documents_root / kind)
    matches = [p for p in folder.iterdir() if p.is_file()
               and p.suffix.casefold() in {".pdf", ".docx", ".txt", ".md"}
               and safe_filename(p.name).casefold() == target]
    if not matches and allow_missing:
        # Preserve the parser's existing missing-file/error and injected-open
        # interface; callers verifying a manifest leave this disabled.
        return confined(documents_root, folder / name)
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous normalized source filename")
    return confined(documents_root, matches[0])


def location(meta: dict) -> str:
    if meta["page"]:
        return f"{meta['source']}, PDF page {meta['page']}"
    return f"{meta['source']}, text block {meta['block']} (no stable page number)"


def validate_ids(proposed_ids: list[str], evidence: list[dict]) -> list[str]:
    allowed = {x["id"] for x in evidence}
    return list(dict.fromkeys(x for x in proposed_ids if x in allowed))
