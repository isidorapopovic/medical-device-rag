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
    file_sha = digest(path.read_bytes())
    relative = f"{kind}/{path.name}"
    warnings = []
    records = []
    ext = path.suffix.casefold()
    if ext == ".pdf":
        pdf = fitz.open(path)
        try:
            for i in range(len(pdf)):
                text = pdf[i].get_text("text", sort=True)
                if not text.strip():
                    warnings.append(f"{relative} page {i+1}: no extractable text (OCR may be needed)")
                for n, chunk in enumerate(chunks(text), 1):
                    records.append(make_record(relative, file_sha, kind, i + 1, n, chunk))
        finally:
            pdf.close()
    elif ext == ".docx":
        doc = Document(path)
        # Word pages are not stable without layout: cite numbered text blocks.
        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                paras.append(" | ".join(cell.text for cell in row.cells))
        for n, paragraph in enumerate(paras, 1):
            for j, chunk in enumerate(chunks(paragraph), 1):
                records.append(make_record(relative, file_sha, kind, 0, n * 1000 + j, chunk))
        if not paras:
            warnings.append(f"{relative}: no extractable paragraphs")
    elif ext in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8-sig")
        for n, chunk in enumerate(chunks(text), 1):
            records.append(make_record(relative, file_sha, kind, 0, n, chunk))
    return records, warnings


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
    all_chunks, warnings, manifest = [], [], []
    for kind in ("legal", "device"):
        folder = DOCS / kind
        folder.mkdir(parents=True, exist_ok=True)
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".pdf", ".docx", ".txt", ".md"}:
                continue
            records, problems = source_records(path, kind)
            all_chunks.extend(records)
            warnings.extend(problems)
            manifest.append({
                "source": f"{kind}/{path.name}", "kind": kind,
                "sha256": digest(path.read_bytes()), "chunks": len(records),
            })
    return all_chunks, warnings, manifest


def location(meta: dict) -> str:
    if meta["page"]:
        return f"{meta['source']}, PDF page {meta['page']}"
    return f"{meta['source']}, text block {meta['block']} (no stable page number)"


def validate_ids(proposed_ids: list[str], evidence: list[dict]) -> list[str]:
    allowed = {x["id"] for x in evidence}
    return list(dict.fromkeys(x for x in proposed_ids if x in allowed))
