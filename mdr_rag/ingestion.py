"""Immutable project-scoped originals, extraction revisions and exact source views."""
import json
import logging
import ntpath
import os
import re
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5
from functools import wraps

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import Document, SourceSpan
from .document_parsers import (Extraction, LocalOCR, MIMES, NORMALIZATION_VERSION, PARSER_VERSION,
                               chunk_ranges, parse_document, sha256)


def safe_filename(value: str) -> str:
    if not isinstance(value, str) or not value or any(0xD800 <= ord(c) <= 0xDFFF or ord(c) < 32 for c in value):
        raise ValueError("Invalid upload filename")
    name = unicodedata.normalize("NFC", ntpath.basename(value.replace("/", "\\"))).strip().rstrip(". ")
    if not name or name in {".", ".."} or len(name) > 200 or re.search(r'[<>:"|?*]', name):
        raise ValueError("Invalid upload filename")
    if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    if Path(name).suffix.casefold() not in MIMES:
        raise ValueError("Supported file types are PDF, DOCX, TXT and MD")
    return name


def confined(root: Path, path: Path) -> Path:
    """Reject existing symlink/junction escapes before any reads or writes."""
    root = root.resolve()
    target = path.resolve()
    if not target.is_relative_to(root):
        raise ValueError("Path escapes the allowed storage root")
    cursor = path.absolute()
    while cursor != root and root in cursor.parents:
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError("Symlink and junction source paths are not allowed")
        cursor = cursor.parent
    return target


def atomic_bytes(path: Path, data: bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable artifact differs; preserve it and investigate")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".ingest-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def ingestion_event(function):
    @wraps(function)
    def wrapper(self, *args, **kwargs):
        started, correlation = time.monotonic(), str(uuid4())
        error, result = None, None
        try:
            result = function(self, *args, **kwargs)
            return result
        except BaseException as exc:
            from .errors import FoundationError
            error = exc.code if isinstance(exc, FoundationError) else "storage_error" if isinstance(exc, OSError) else "parsing_error"
            raise
        finally:
            # Invalid filenames/content rejected before any storage publication
            # do not cause a project directory to be created just for a log.
            if self.directory.exists():
                from .telemetry import emit
                handler = logging.FileHandler(self._path("ingestion-events.jsonl"), encoding="utf-8")
                logger = logging.Logger("ingestion." + correlation)
                logger.addHandler(handler)
                try:
                    emit(correlation, self.project_key, "ingestion", outcome="failed" if error else "completed",
                         error_code=error, elapsed_ms=max(0, int((time.monotonic()-started)*1000)),
                         source_counts=len(result[0].spans) if result else 0, logger=logger)
                finally:
                    handler.close()
    return wrapper


class IngestedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: Literal[1] = 1
    document: Document
    extraction: Extraction
    spans: list[SourceSpan]
    span_units: dict[str, int]
    parser_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def integrity(self):
        if len({s.id for s in self.spans}) != len(self.spans) or set(self.span_units) != {s.id for s in self.spans}:
            raise ValueError("Invalid or duplicate span inventory")
        for span in self.spans:
            index = self.span_units[span.id]
            if not 1 <= index <= len(self.extraction.units):
                raise ValueError("Unknown extraction unit")
            unit = self.extraction.units[index - 1]
            if (span.document_id != self.document.id or span.document_version != self.document.version
                    or span.physical_page_1based != unit.physical_page or span.block_index != unit.index
                    or unit.text[span.start:span.end] != span.text
                    or span.id != span_id(self.document, unit.index, span.start, span.end, span.text, self.parser_fingerprint)):
                raise ValueError("Source span document, version, locator or text mismatch")
        return self


def parser_fingerprint(ocr_enabled: bool = False, ocr_identity: str = "unavailable") -> str:
    import pymupdf
    from importlib.metadata import version
    return sha256(json.dumps([PARSER_VERSION, NORMALIZATION_VERSION, pymupdf.VersionBind,
                              version("python-docx"), ocr_enabled, ocr_identity], separators=(",", ":")).encode())


def span_id(document: Document, unit_index: int, start: int, end: int, text: str, fingerprint: str) -> str:
    return "SP-" + sha256(json.dumps([str(document.id), document.version, document.sha256, fingerprint,
                                      unit_index, start, end, sha256(text.encode("utf-8"))]).encode())


def build_manifest(document: Document, extraction: Extraction, fingerprint: str) -> IngestedDocument:
    spans, span_units = [], {}
    for unit in extraction.units:
        if "unreadable_text" in unit.flags or "page_extraction_failed" in unit.flags:
            continue
        for start, end in chunk_ranges(unit.text):
            text = unit.text[start:end]
            key = span_id(document, unit.index, start, end, text, fingerprint)
            spans.append(SourceSpan(id=key, document_id=document.id, document_version=document.version,
                text_hash=sha256(text.encode("utf-8")), extraction_engine=extraction.engine,
                extraction_version=extraction.parser_version, section_path=["H-" + sha256(s.encode("utf-8"))[:16] for s in unit.sections],
                physical_page_1based=unit.physical_page, block_index=unit.index, start=start, end=end, text=text,
                quality_flags=unit.flags))
            span_units[key] = unit.index
    return IngestedDocument(document=document, extraction=extraction, spans=spans, span_units=span_units,
                            parser_fingerprint=fingerprint)


def records_from_manifest(manifest: IngestedDocument, manifest_hash: str | None = None) -> list[dict]:
    from .core import make_record
    doc, result = manifest.document, []
    for order, span in enumerate(manifest.spans, 1):
        unit = manifest.extraction.units[manifest.span_units[span.id] - 1]
        record = make_record(f"{doc.collection}/{doc.original_name}", doc.sha256, doc.collection,
                             span.physical_page_1based or 0, order, span.text)
        record["meta"].update(document_id=str(doc.id), document_version=doc.version, source_span_id=span.id,
            normalization_version=NORMALIZATION_VERSION, parser_fingerprint=manifest.parser_fingerprint,
            unit_index=unit.index, normalized_start=span.start, normalized_end=span.end,
            project_key=sha256(doc.project_id.encode("utf-8")), text_sha256=span.text_hash,
            extraction_method=unit.method)
        if manifest_hash:
            record["meta"]["manifest_sha256"] = manifest_hash
        result.append(record)
    return result


class IngestionStore:
    def __init__(self, root: Path, project_id: str = "local"):
        if not re.fullmatch(r"[\w.-]{1,128}", project_id) or project_id in {".", ".."}:
            raise ValueError("Invalid project ID")
        self.root = root.resolve()
        self.project_id = project_id
        self.project_key = sha256(project_id.encode("utf-8"))
        self.directory = confined(self.root, self.root / self.project_key)

    def _path(self, *parts: str) -> Path:
        return confined(self.root, self.directory.joinpath(*parts))

    @ingestion_event
    def ingest(self, kind: str, filename: str, content: bytes, *, ocr_enabled: bool = False,
               ocr: LocalOCR | None = None) -> tuple[IngestedDocument, str]:
        if kind not in {"legal", "device"}:
            raise ValueError("Document type must be legal or device")
        name = safe_filename(filename)
        # All content validation/parsing is local and occurs before publication.
        from .document_parsers import validate_content
        validate_content(content, Path(name).suffix.casefold())
        doc_id = uuid5(NAMESPACE_URL, f"medical-rag:{self.project_key}:{kind}:{name.casefold()}")
        fingerprint = parser_fingerprint(ocr_enabled, getattr(ocr, "identity", "unavailable"))
        checksum = sha256(content)
        from .report_state import exclusive_lock
        with exclusive_lock(self._path("ingestion.lock")):
            head_path = self._path("heads", str(doc_id) + ".json")
            head = json.loads(head_path.read_text(encoding="utf-8")) if head_path.exists() else None
            if head and head["sha256"] == checksum and head["parser_fingerprint"] == fingerprint:
                result = self.load(head["manifest_sha256"])
                if result.document.id != doc_id or result.document.collection != kind:
                    raise ValueError("Document head identity mismatch")
                self.original(result)  # Do not silently trust a missing/tampered original.
                return result, head["manifest_sha256"]
            extraction = parse_document(content, Path(name).suffix, ocr_enabled=ocr_enabled, ocr=ocr)
            created_at = self.load(head["manifest_sha256"]).document.created_at if head and head["sha256"] == checksum else datetime.now(timezone.utc)
            document = Document(id=doc_id, project_id=self.project_id, collection=kind, original_name=name,
                mime=extraction.mime, sha256=checksum, byte_size=len(content),
                version=(head["version"] if head and head["sha256"] == checksum else head["version"] + 1 if head else 1),
                created_at=created_at, upload_status="accepted")
            result = build_manifest(document, extraction, fingerprint)
            payload = result.model_dump_json().encode("utf-8")
            manifest_hash = sha256(payload)
            # Originals and extraction snapshots are immutable. An interrupted
            # publish may leave unreachable content blobs, never a partial head.
            atomic_bytes(self._path("originals", checksum + Path(name).suffix.casefold()), content, immutable=True)
            atomic_bytes(self._path("manifests", manifest_hash + ".json"), payload, immutable=True)
            atomic_bytes(head_path, json.dumps(dict(version=document.version, sha256=checksum,
                parser_fingerprint=fingerprint, manifest_sha256=manifest_hash)).encode("utf-8"))
            return result, manifest_hash

    def ingest_path(self, path: Path, kind: str, *, allowed_root: Path) -> tuple[IngestedDocument, str]:
        path = confined(allowed_root, path)
        from .document_parsers import MAX_BYTES
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("upload_exceeds_50_mib")
        return self.ingest(kind, path.name, path.read_bytes())

    def load(self, manifest_hash: str) -> IngestedDocument:
        if not re.fullmatch(r"[a-f0-9]{64}", manifest_hash):
            raise ValueError("Invalid manifest ID")
        path = self._path("manifests", manifest_hash + ".json")
        if path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("Extraction manifest resource limit")
        data = path.read_bytes()
        if sha256(data) != manifest_hash:
            raise ValueError("Extraction manifest hash mismatch")
        try:
            result = IngestedDocument.model_validate_json(data)
        except ValueError:
            raise ValueError("Invalid extraction manifest") from None
        if result.document.project_id != self.project_id:
            raise ValueError("Project scope mismatch")
        return result

    def original(self, manifest: IngestedDocument) -> Path:
        if manifest.document.project_id != self.project_id:
            raise ValueError("Project scope mismatch")
        path = self._path("originals", manifest.document.sha256 + Path(manifest.document.original_name).suffix.casefold())
        if path.stat().st_size != manifest.document.byte_size:
            raise ValueError("Original document hash mismatch")
        if sha256(path.read_bytes()) != manifest.document.sha256:
            raise ValueError("Original document hash mismatch")
        return path

    def view(self, manifest_hash: str, source_span_id: str, *, start: int = 0, end: int | None = None,
             context: int = 160) -> dict:
        if not 0 <= context <= 2000:
            raise ValueError("Context budget must be 0..2000 characters")
        manifest = self.load(manifest_hash)
        span = next((item for item in manifest.spans if item.id == source_span_id), None)
        if span is None:
            raise ValueError("Unknown source span")
        end = len(span.text) if end is None else end
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(span.text):
            raise ValueError("Invalid citation offsets")
        unit = manifest.extraction.units[manifest.span_units[span.id] - 1]
        left, right = span.start + start, span.start + end
        raw_start, raw_end = unit.offsets[left][0], unit.offsets[right - 1][1]
        return dict(document=manifest.document.model_dump(mode="json"), source_span_id=span.id,
            original_path=str(self.original(manifest)), physical_page=unit.physical_page,
            block_index=unit.index, paragraph_index=unit.paragraph_index, table_index=unit.table_index,
            row_index=unit.row_index, cell_index=unit.cell_index, sections=unit.sections,
            line_start=unit.line_start, line_end=unit.line_end, raw_start=unit.raw_start + raw_start,
            raw_end=unit.raw_start + raw_end, normalization_version=NORMALIZATION_VERSION,
            document_status=manifest.extraction.status, diagnostics=manifest.extraction.diagnostics,
            exact_quote=span.text[start:end], raw_excerpt=unit.raw_text[raw_start:raw_end],
            surrounding_context=unit.raw_text[max(0, raw_start-context):raw_end+context],
            extraction_method=unit.method, quality_flags=unit.flags, verification="unverified_source_extraction")

    def view_snapshot(self, passage, *, start: int = 0, end: int | None = None, context: int = 160) -> dict:
        """Resolve a canonical SourceBuffer passage back to its immutable original."""
        from .source_buffer import checked_passage
        passage = checked_passage(passage.model_dump() if hasattr(passage, "model_dump") else passage)
        ref = passage.ingestion
        if ref is None:
            raise ValueError("Legacy snapshot has no archived-original reference")
        if ref.project_key != self.project_key:
            raise ValueError("Project scope mismatch")
        manifest = self.load(ref.manifest_sha256)
        matching = next((record for record in records_from_manifest(manifest, ref.manifest_sha256)
                         if record["meta"]["source_span_id"] == ref.source_span_id), None)
        if matching is None or (matching["id"], matching["text"], matching["meta"]["source"], matching["meta"]["sha256"],
                               matching["meta"]["page"], matching["meta"]["block"]) != (
                passage.chunk_id, passage.text, passage.source, passage.file_sha256, passage.page, passage.block):
            raise ValueError("Archived source does not match the cited snapshot")
        if any(matching["meta"][key] != getattr(ref, key) for key in type(ref).model_fields):
            raise ValueError("Archived source reference mismatch")
        return self.view(ref.manifest_sha256, ref.source_span_id, start=start, end=end, context=context)


def parse_records(path: Path, kind: str) -> tuple[list[dict], list[str]]:
    """Read-only compatibility facade used by previews; index ingestion archives originals."""
    from .document_parsers import MAX_BYTES
    if kind not in {"legal", "device"}:
        raise ValueError("Document type must be legal or device")
    path = confined(path.parent, path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("upload_exceeds_50_mib")
    content = path.read_bytes()
    name = safe_filename(path.name)
    doc = Document(id=uuid5(NAMESPACE_URL, f"preview:{kind}:{name}"), project_id="preview", collection=kind,
                   original_name=name, mime=MIMES[Path(name).suffix.casefold()], sha256=sha256(content),
                   byte_size=len(content), created_at=datetime.now(timezone.utc), version=1)
    extraction = parse_document(content, Path(name).suffix)
    manifest = build_manifest(doc, extraction, parser_fingerprint())
    return records_from_manifest(manifest), extraction_warnings(manifest)


def extraction_warnings(manifest: IngestedDocument) -> list[str]:
    warnings = list(manifest.extraction.diagnostics)
    for unit in manifest.extraction.units:
        warnings.extend(f"{flag}: physical page {unit.physical_page}" if unit.physical_page else f"{flag}: block {unit.index}"
                        for flag in unit.flags)
    if manifest.extraction.status != "parsed":
        warnings.insert(0, "extraction_status=" + manifest.extraction.status)
    return warnings
