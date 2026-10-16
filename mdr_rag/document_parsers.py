"""Bounded offline parsing. Uploaded text is data, never instructions or configuration."""
import hashlib
import io
import platform
import re
import unicodedata
import zipfile
from typing import Literal, Protocol

import pymupdf
from docx import Document
from docx import __version__ as DOCX_VERSION
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import FoundationError

MAX_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_TEXT_CHARS = 5_000_000
MAX_PAGES = 2000
MAX_UNITS = 20000
NORMALIZATION_VERSION = "nfc-horizontal-space-soft-hyphen-v1"
PARSER_VERSION = "structural-ingestion-v1"
MIMES = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ".txt": "text/plain", ".md": "text/markdown"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ParserError(ValueError):
    """Only fixed diagnostics cross parser boundaries, never parser exception bodies."""


class ParsedUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    index: int = Field(ge=1)
    physical_page: int | None = Field(default=None, ge=1)
    paragraph_index: int | None = Field(default=None, ge=1)
    table_index: int | None = Field(default=None, ge=1)
    row_index: int | None = Field(default=None, ge=1)
    cell_index: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    raw_start: int = Field(default=0, ge=0)
    raw_text: str
    text: str
    offsets: list[tuple[int, int]]
    sections: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    method: Literal["native", "ocr"] = "native"

    @model_validator(mode="after")
    def integrity(self):
        if len(self.raw_text) > MAX_TEXT_CHARS:
            raise ValueError("Extraction text limit exceeded")
        text, offsets = normalize(self.raw_text)
        if self.text != text or self.offsets != offsets:
            raise ValueError("Normalization text or offset map mismatch")
        return self


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    mime: str
    engine: str
    engine_version: str
    parser_version: str = PARSER_VERSION
    normalization_version: str = NORMALIZATION_VERSION
    status: Literal["uploaded", "parsed", "partial", "failed", "needs_ocr"]
    diagnostics: list[str] = Field(default_factory=list)
    units: list[ParsedUnit] = Field(default_factory=list)

    @model_validator(mode="after")
    def limits(self):
        if sum(len(unit.raw_text) for unit in self.units) > MAX_TEXT_CHARS:
            raise ValueError("Extraction text limit exceeded")
        if [u.index for u in self.units] != list(range(1, len(self.units) + 1)):
            raise ValueError("Extraction units are not consecutive")
        if self.status == "parsed" and not any(unit.text.strip() for unit in self.units):
            raise ValueError("Empty extraction cannot be parsed successfully")
        return self


class LocalOCR(Protocol):
    """Only an explicitly injected local engine; no download or remote OCR fallback."""
    def extract(self, page: pymupdf.Page) -> str: ...


class TesseractOCR:
    identity = "pymupdf-tesseract-eng-150dpi-v1"

    def extract(self, page: pymupdf.Page) -> str:
        if page.rect.width * page.rect.height * (150 / 72) ** 2 > 20_000_000:
            raise ParserError("ocr_pixel_limit")
        from .runtime import provider_scope
        with provider_scope() as run:
            def extract_locally(timeout):
                textpage = page.get_textpage_ocr(language="eng", dpi=150, full=True)
                return {"text": page.get_text("text", textpage=textpage), "prompt_eval_count": 0, "eval_count": 0}
            return run.call("ocr", extract_locally, input_tokens=0, output_tokens=0,
                            prompt_chars=0, source_counts=1)["text"]


def normalize(raw: str) -> tuple[str, list[tuple[int, int]]]:
    """NFC clusters, CR/LF and horizontal whitespace, preserving case and line breaks.

    Each normalized character maps to its exact half-open raw character envelope.
    Soft hyphens are omitted; no casefolding or invented source text is performed.
    """
    output, offsets = [], []
    position = 0
    while position < len(raw):
        start, end = position, position + 1
        char = raw[start]
        if char == "\u00ad":
            position = end
            continue
        if 0xD800 <= ord(char) <= 0xDFFF or char == "\x00":
            raise ParserError("invalid_unicode")
        if char in {"\r", "\n"}:
            if char == "\r" and raw[end:end + 1] == "\n":
                end += 1
            value = "\n"
        elif char.isspace():
            while end < len(raw) and raw[end].isspace() and raw[end] not in {"\r", "\n"}:
                end += 1
            value = " "
        else:
            while end < len(raw):
                if end - start > 32:
                    raise ParserError("unicode_cluster_limit")
                candidate = unicodedata.normalize("NFC", raw[start:end] + raw[end])
                current = unicodedata.normalize("NFC", raw[start:end])
                if unicodedata.category(raw[end]).startswith("M") or len(candidate) < len(current) + 1:
                    end += 1
                else:
                    break
            value = unicodedata.normalize("NFC", raw[start:end])
        output.extend(value)
        offsets.extend([(start, end)] * len(value))
        position = end
    return "".join(output), offsets


def unit(raw: str, index: int, **kwargs) -> ParsedUnit:
    if index > MAX_UNITS or len(raw) > MAX_TEXT_CHARS:
        raise ParserError("extraction_resource_limit")
    text, offsets = normalize(raw)
    return ParsedUnit(index=index, raw_text=raw, text=text, offsets=offsets, **kwargs)


def chunk_ranges(text: str, size: int = 2000, overlap: int = 250):
    if not 0 <= overlap < size:
        raise ValueError("Invalid chunk bounds")
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            split = text.rfind("\n", start + int(size * .65), end)
            if split < 0:
                split = text.rfind(" ", start + int(size * .75), end)
            if split > start:
                end = split + 1
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            yield left, right
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def validate_content(content: bytes, suffix: str) -> str:
    if not isinstance(content, bytes) or not content:
        raise ParserError("empty_upload")
    if len(content) > MAX_BYTES:
        raise ParserError("upload_exceeds_50_mib")
    if suffix not in MIMES:
        raise ParserError("unsupported_file_type")
    is_pdf = content[:1024].lstrip().startswith(b"%PDF-")
    is_zip = content.startswith(b"PK")
    if suffix == ".pdf" and not is_pdf or suffix == ".docx" and not is_zip:
        raise ParserError("mime_mismatch")
    if suffix in {".txt", ".md"} and (is_pdf or is_zip or b"\x00" in content and not content.startswith((b"\xff\xfe", b"\xfe\xff"))):
        raise ParserError("mime_mismatch")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                infos = archive.infolist()
                if (len(infos) > 5000 or len({item.filename for item in infos}) != len(infos)
                        or sum(item.file_size for item in infos) > MAX_EXPANDED_BYTES
                        or any(item.file_size > 1_000_000 and item.file_size > 200 * max(1, item.compress_size) for item in infos)):
                    raise ParserError("unsafe_docx_archive")
                if not {"[Content_Types].xml", "word/document.xml"} <= {item.filename for item in infos}:
                    raise ParserError("mime_mismatch")
                if any(".." in item.filename.replace("\\", "/").split("/") or item.filename.startswith(("/", "\\"))
                       or item.flag_bits & 1 for item in infos):
                    raise ParserError("unsafe_docx_archive")
                for item in infos:
                    if item.filename.endswith(".xml") and item.file_size <= MAX_EXPANDED_BYTES:
                        xml = archive.read(item)
                        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper() or b"\x00" in xml:
                            raise ParserError("unsafe_docx_xml")
        except (zipfile.BadZipFile, OSError, RuntimeError):
            raise ParserError("damaged_docx") from None
    return MIMES[suffix]


def parse_document(content: bytes, suffix: str, *, ocr_enabled: bool = False, ocr: LocalOCR | None = None) -> Extraction:
    suffix = suffix.casefold()
    mime = validate_content(content, suffix)
    if suffix == ".pdf":
        return parse_pdf(content, ocr_enabled=ocr_enabled, ocr=ocr)
    if suffix == ".docx":
        return parse_docx(content)
    diagnostics = []
    try:
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            raw = content.decode("utf-16")
            diagnostics.append("unexpected_encoding_utf16")
        else:
            raw = content.decode("utf-8-sig")
    except UnicodeError:
        return Extraction(mime=mime, engine="python-codecs", engine_version=platform.python_version(), status="failed", diagnostics=["unexpected_encoding"])
    if len(raw) > MAX_TEXT_CHARS:
        raise ParserError("extraction_text_limit")
    units, sections, start, lines = [], [], 0, raw.splitlines(keepends=True)
    # Blank-line-delimited blocks preserve global raw char and line offsets.
    block_start, first_line, pending = 0, 1, []
    for number, line in enumerate(lines, 1):
        heading = re.match(r"^\s*(#{1,6})\s+(.+)", line) if suffix == ".md" else None
        if heading and pending:
            units.append(unit("".join(pending), len(units) + 1, line_start=first_line, line_end=number - 1,
                              raw_start=block_start, sections=list(sections)))
            pending = []
        if heading:
            level = len(heading[1])
            sections = sections[:level - 1] + [heading[2].strip()]
        if not pending:
            block_start, first_line = start, number
        pending.append(line)
        start += len(line)
        if not line.strip() or number == len(lines):
            text = "".join(pending)
            units.append(unit(text, len(units) + 1, line_start=first_line, line_end=number,
                              raw_start=block_start, sections=list(sections)))
            pending = []
        if len(units) > MAX_UNITS:
            raise ParserError("extraction_unit_limit")
    return Extraction(mime=mime, engine="python-codecs", engine_version=platform.python_version(), units=units,
                      status="parsed" if any(u.text.strip() for u in units) else "failed",
                      diagnostics=diagnostics or ([] if any(u.text.strip() for u in units) else ["empty_text"]))


def parse_pdf(content: bytes, *, ocr_enabled: bool, ocr: LocalOCR | None) -> Extraction:
    diagnostics, units = [], []
    try:
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            if pdf.is_repaired:
                diagnostics.append("repaired_pdf_unverified")
            if pdf.needs_pass:
                return Extraction(mime=MIMES[".pdf"], engine="pymupdf", engine_version=pymupdf.VersionBind,
                                  status="failed", diagnostics=["password_protected_pdf"])
            if not 0 < len(pdf) <= MAX_PAGES:
                raise ParserError("pdf_page_limit_or_empty")
            total = 0
            sections = []
            for index, page in enumerate(pdf, 1):
                flags, method = [], "native"
                try:
                    raw = page.get_text("text", sort=True)
                    if page.rotation:
                        flags.append("rotated_page")
                    if not raw.strip():
                        flags.append("needs_ocr")
                        if ocr_enabled and ocr is not None and index <= 20:
                            try:
                                raw = ocr.extract(page)
                                if not isinstance(raw, str):
                                    raise ParserError("invalid_ocr_output")
                                if raw.strip():
                                    method = "ocr"
                                    flags = ["ocr_unverified"]
                                else:
                                    flags.append("poor_ocr")
                            except FoundationError:
                                raise
                            except Exception:
                                raw = ""
                                flags.append("ocr_failed")
                        elif ocr_enabled:
                            flags.append("ocr_unavailable")
                    if "\ufffd" in raw:
                        flags.append("replacement_characters")
                        if raw.count("\ufffd") / max(1, len(raw.strip())) > .05:
                            flags.extend(["unreadable_text", "needs_ocr"])
                    # Table reconstruction is deliberately not represented as verified.
                    flags.append("pdf_tables_not_structurally_verified")
                    visible = next((line.strip() for line in raw.splitlines() if line.strip()), "")
                    if re.match(r"^(?:ANNEX\b|ARTICLE\b|Article\s+\d|[A-Z][A-Z\s]{3,80}$)", visible):
                        sections = [visible]
                    total += len(raw)
                    if total > MAX_TEXT_CHARS:
                        raise ParserError("extraction_text_limit")
                    units.append(unit(raw, index, physical_page=index, flags=flags, method=method, sections=list(sections)))
                except (ParserError, FoundationError):
                    raise
                except Exception:
                    units.append(unit("", index, physical_page=index, flags=["page_extraction_failed"]))
    except (ParserError, FoundationError):
        raise
    except Exception:
        return Extraction(mime=MIMES[".pdf"], engine="pymupdf", engine_version=pymupdf.VersionBind,
                          status="failed", diagnostics=["damaged_pdf"])
    flags = {flag for u in units for flag in u.flags}
    readable = any(u.text.strip() and "unreadable_text" not in u.flags for u in units)
    incomplete = bool(diagnostics or flags & {"needs_ocr", "page_extraction_failed", "ocr_unverified", "replacement_characters"})
    status = "partial" if readable and incomplete else "parsed" if readable else "needs_ocr"
    return Extraction(mime=MIMES[".pdf"], engine="pymupdf", engine_version=pymupdf.VersionBind,
                      status=status, units=units, diagnostics=diagnostics)


def parse_docx(content: bytes) -> Extraction:
    units, sections, paragraph_index, table_index = [], [], 0, 0
    diagnostics = []
    text_total = 0
    try:
        doc = Document(io.BytesIO(content))
        for child in doc.element.body.iterchildren():
            before = len(units)
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                paragraph_index += 1
                paragraph = Paragraph(child, doc)
                style = paragraph.style.name if paragraph.style else ""
                if style.startswith("Heading") and paragraph.text.strip():
                    match = re.search(r"\d+", style)
                    level = int(match[0]) if match else 1
                    sections = sections[:level - 1] + [paragraph.text.strip()]
                units.append(unit(paragraph.text, len(units) + 1, paragraph_index=paragraph_index, sections=list(sections)))
            elif tag == "tbl":
                table_index += 1
                table = Table(child, doc)
                for row_index, row in enumerate(table.rows, 1):
                    seen_cells = set()
                    for cell_index, cell in enumerate(row.cells, 1):
                        if cell._tc in seen_cells:
                            continue
                        seen_cells.add(cell._tc)
                        flags = ["nested_tables_not_extracted"] if cell.tables else []
                        units.append(unit(cell.text, len(units) + 1, table_index=table_index,
                                          row_index=row_index, cell_index=cell_index, sections=list(sections), flags=flags))
            text_total += sum(len(u.raw_text) for u in units[before:])
            if text_total > MAX_TEXT_CHARS:
                raise ParserError("extraction_text_limit")
            if len(units) > MAX_UNITS:
                raise ParserError("extraction_unit_limit")
        # Headers/footers, drawings and embedded objects are not hidden evidence.
        diagnostics.append("docx_headers_footers_drawings_not_extracted")
    except ParserError:
        raise
    except Exception:
        return Extraction(mime=MIMES[".docx"], engine="python-docx", engine_version=DOCX_VERSION, status="failed", diagnostics=["damaged_docx"])
    readable = any(u.text.strip() for u in units)
    return Extraction(mime=MIMES[".docx"], engine="python-docx", engine_version=DOCX_VERSION, units=units,
                      status="partial" if readable else "failed", diagnostics=diagnostics + ([] if readable else ["empty_docx"]))
