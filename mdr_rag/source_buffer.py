"""Immutable indexed-text snapshots and deterministic raw-span provenance.

Offsets address Python characters in the exact indexed text, not the PDF binary.
Snapshot identity includes corpus, file hash, physical locator and extraction
version. A genuine quote establishes provenance, not semantic entailment.
"""
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .core import digest, norm

EXTRACTION_VERSION = "character-2000-overlap250-v1"
INDEX_VERSION = "chroma-medical_mdr_evidence-v1"


def content_hash(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8"))


class ImmutableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class SourcePassage(ImmutableModel):
    schema_version: Literal[1] = 1
    buffer_id: str
    chunk_id: str = Field(min_length=1)
    kind: Literal["legal", "device"]
    source: str = Field(min_length=1)
    file_sha256: str = Field(min_length=1)
    page: int = Field(ge=0)
    block: int = Field(ge=1)
    locator: Literal["pdf_page", "text_block"]
    text: str = Field(min_length=1)
    text_sha256: str
    extraction_version: str = Field(min_length=1)
    index_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def integrity(self):
        if not self.source.startswith(self.kind + "/"):
            raise ValueError("Source corpus does not match passage kind")
        if self.locator != ("pdf_page" if self.page else "text_block"):
            raise ValueError("PDF page and text-block locators cannot be interchanged")
        suffix = Path(self.source).suffix.lower()
        if suffix == ".pdf" and self.page < 1:
            raise ValueError("PDF passage requires a physical page")
        if suffix in {".docx", ".txt", ".md"} and self.page != 0:
            raise ValueError("DOCX/text passage has no stable physical page")
        if self.text_sha256 != digest(self.text.encode("utf-8")):
            raise ValueError("Passage text hash mismatch")
        payload = self.model_dump(exclude={"buffer_id"})
        if self.buffer_id != "SB-" + content_hash(payload):
            raise ValueError("Passage content identity mismatch")
        return self


class RawSpan(ImmutableModel):
    buffer_id: str
    exact_quote: str = Field(min_length=1)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    resolution: Literal["exact", "legacy_normalized_mapping"] = "exact"


class ClaimEvidenceLink(RawSpan):
    claim_id: str = Field(min_length=1)
    chunk_id: str
    kind: Literal["legal", "device"]
    source: str
    file_sha256: str
    text_sha256: str
    page: int
    block: int
    locator: Literal["pdf_page", "text_block"]
    purpose: Literal["legal_basis", "device_support", "contradiction", "applicability"]
    raw_span_verified: Literal[True] = True


class PresentedPassage(ImmutableModel):
    buffer_id: str
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    text_sha256: str


class ModelCallTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str = Field(default_factory=lambda: "call-" + uuid4().hex)
    stage: str
    model: str
    instructions_sha256: str
    input_sha256: str
    retrieved_buffer_ids: list[str] = Field(default_factory=list)
    presented: list[PresentedPassage] = Field(default_factory=list)
    outcome: Literal["started", "completed", "failed"] = "started"


def checked_passage(value) -> SourcePassage:
    try:
        return SourcePassage.model_validate_json(value) if isinstance(value, str) else SourcePassage.model_validate(value)
    except (ValueError, TypeError) as exc:
        # Pydantic diagnostics can include confidential passage text.
        raise ValueError("Invalid source snapshot metadata, text hash or content identity; no snapshot was overwritten") from exc


def normalized_offsets(text: str):
    """Return core.norm(text) and reversible character ranges (including casefold expansion)."""
    chars, ranges = [], []
    whitespace = None
    for index, original in enumerate(text):
        if original == "\u00ad":
            continue
        char = "-" if original == "\u2010" else original
        if char.isspace():
            if chars:
                whitespace = (whitespace[0] if whitespace else index, index + 1)
            continue
        if whitespace is not None:
            chars.append(" ")
            ranges.append(whitespace)
            whitespace = None
        for folded in char.casefold():
            chars.append(folded)
            ranges.append((index, index + 1))
    return "".join(chars), ranges


def occurrences(text: str, quote: str):
    positions = []
    position = text.find(quote)
    while position >= 0:
        positions.append((position, position + len(quote)))
        position = text.find(quote, position + 1)
    return positions


class SourceBuffer:
    def __init__(self, snapshots=None, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else None
        self._passages = {}
        for key, item in (snapshots or {}).items():
            passage = checked_passage(item)
            if key != passage.buffer_id:
                raise ValueError("Snapshot key differs from content identity")
            self._passages[key] = passage

    @property
    def snapshots(self):
        return dict(self._passages)

    def add_passage(self, record, extraction_version=EXTRACTION_VERSION, index_version=INDEX_VERSION) -> str:
        if isinstance(record, SourcePassage):
            passage = checked_passage(record.model_dump())
        else:
            meta = record["meta"]
            kind = meta.get("kind") or meta["source"].split("/", 1)[0]
            payload = {"schema_version": 1, "chunk_id": record["id"], "kind": kind,
                       "source": meta["source"], "file_sha256": meta["sha256"],
                       "page": meta["page"], "block": meta["block"],
                       "locator": "pdf_page" if meta["page"] else "text_block",
                       "text": record["text"], "text_sha256": digest(record["text"].encode("utf-8")),
                       "extraction_version": extraction_version, "index_version": index_version}
            passage = checked_passage({"buffer_id": "SB-" + content_hash(payload), **payload})
        if self.directory is not None:
            from .report_state import atomic_write, exclusive_lock

            with exclusive_lock(self.directory / "source_buffer.lock"):
                path = self.directory / (passage.buffer_id + ".json")
                if path.exists():
                    saved = checked_passage(path.read_text(encoding="utf-8"))
                    if saved != passage:
                        raise ValueError("Existing immutable snapshot differs; it was not overwritten")
                else:
                    atomic_write(path, passage.model_dump_json(indent=2))
        existing = self._passages.get(passage.buffer_id)
        if existing is not None and existing != passage:
            raise ValueError("Immutable snapshot collision")
        self._passages[passage.buffer_id] = passage
        return passage.buffer_id

    def get_passage(self, buffer_id: str) -> SourcePassage:
        if not re.fullmatch(r"SB-[0-9a-f]{64}", buffer_id):
            raise ValueError("Unknown or invalid buffer ID")
        if buffer_id not in self._passages and self.directory is not None:
            path = self.directory / (buffer_id + ".json")
            if path.exists():
                saved = checked_passage(path.read_text(encoding="utf-8"))
                if saved.buffer_id != buffer_id:
                    raise ValueError("Stored snapshot identity mismatch")
                self._passages[buffer_id] = saved
        if buffer_id not in self._passages:
            raise ValueError("Unknown buffer ID")
        return self._passages[buffer_id]

    def resolve_quote(self, buffer_id, quote, offsets=None) -> RawSpan:
        passage = self.get_passage(buffer_id)
        if not isinstance(quote, str) or not quote:
            raise ValueError("Quote must be nonempty")
        if offsets is not None:
            start, end = offsets
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(passage.text):
                raise ValueError("Invalid raw quote offsets")
            if passage.text[start:end] != quote:
                raise ValueError("Raw quote does not match supplied offsets")
        else:
            matches = occurrences(passage.text, quote)
            if not matches:
                raise ValueError("Quote is absent from the raw passage")
            if len(matches) != 1:
                raise ValueError("Ambiguous raw quote; supply explicit chosen offsets")
            start, end = matches[0]
        return RawSpan(buffer_id=buffer_id, exact_quote=quote, start=start, end=end)

    def resolve_legacy_quote(self, buffer_id, quote, offsets=None) -> RawSpan:
        """Map a normalized legacy anchor to a unique raw span; never publish the normalized text as exact."""
        passage = self.get_passage(buffer_id)
        target = norm(quote)
        if not target:
            raise ValueError("Legacy quote must be nonempty")
        if offsets is not None:
            start, end = offsets
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(passage.text):
                raise ValueError("Invalid legacy quote offsets")
            if norm(passage.text[start:end]) != target:
                raise ValueError("Legacy quote does not match chosen raw span")
        else:
            # Exact raw quotes still obey the repeated-quote ambiguity rule.
            if occurrences(passage.text, quote):
                return self.resolve_quote(buffer_id, quote)
            normalized, offsets_map = normalized_offsets(passage.text)
            matches = set()
            for left, right in occurrences(normalized, target):
                start, end = offsets_map[left][0], offsets_map[right - 1][1]
                if norm(passage.text[start:end]) == target:
                    matches.add((start, end))
            if not matches:
                raise ValueError("Legacy quote cannot be mapped to a raw span")
            if len(matches) != 1:
                raise ValueError("Ambiguous normalized quote; supply explicit chosen offsets")
            start, end = matches.pop()
        return RawSpan(buffer_id=buffer_id, exact_quote=passage.text[start:end], start=start, end=end,
                       resolution="legacy_normalized_mapping" if passage.text[start:end] != quote else "exact")

    def make_link(self, span: RawSpan, claim_id, purpose) -> ClaimEvidenceLink:
        passage = self.get_passage(span.buffer_id)
        self.resolve_quote(span.buffer_id, span.exact_quote, (span.start, span.end))
        fields = {key: getattr(passage, key) for key in (
            "chunk_id", "kind", "source", "file_sha256", "text_sha256", "page", "block", "locator")}
        return ClaimEvidenceLink(**span.model_dump(), claim_id=claim_id, purpose=purpose, **fields)

    def presented(self, buffer_id, start=0, end=None) -> PresentedPassage:
        passage = self.get_passage(buffer_id)
        end = len(passage.text) if end is None else end
        self.resolve_quote(buffer_id, passage.text[start:end], (start, end))
        return PresentedPassage(buffer_id=buffer_id, start=start, end=end,
                                text_sha256=digest(passage.text[start:end].encode("utf-8")))

    def validate_presented(self, item: PresentedPassage):
        passage = self.get_passage(item.buffer_id)
        if not 0 <= item.start < item.end <= len(passage.text):
            raise ValueError("Presented range is outside the passage")
        if digest(passage.text[item.start:item.end].encode("utf-8")) != item.text_sha256:
            raise ValueError("Presented range hash mismatch")
        return True

    def validate_link(self, link, presented=None) -> bool:
        try:
            link = ClaimEvidenceLink.model_validate(link)
        except ValueError as exc:
            raise ValueError("Invalid evidence-link schema or raw offsets") from exc
        passage = self.get_passage(link.buffer_id)
        for key in ("chunk_id", "kind", "source", "file_sha256", "text_sha256", "page", "block", "locator"):
            if getattr(link, key) != getattr(passage, key):
                raise ValueError("Evidence identity/hash/locator mismatch")
        self.resolve_quote(link.buffer_id, link.exact_quote, (link.start, link.end))
        if link.purpose == "device_support" and link.kind != "device":
            raise ValueError("Device support must reference the device corpus")
        if link.purpose == "legal_basis" and link.kind != "legal":
            raise ValueError("Legal basis must reference the legal corpus")
        if presented is not None:
            for item in presented:
                self.validate_presented(item)
            if not any(item.buffer_id == link.buffer_id and item.start <= link.start < link.end <= item.end
                       for item in presented):
                raise ValueError("Cited span was not presented to this model call")
        return True


def call_trace(buffer, stage, model, instructions, input_text, retrieved, presented):
    for buffer_id in retrieved:
        buffer.get_passage(buffer_id)
    for item in presented:
        buffer.validate_presented(item)
        passage = buffer.get_passage(item.buffer_id)
        if passage.text[item.start:item.end] not in input_text or passage.chunk_id not in input_text:
            raise ValueError("Declared source span/ID is absent from the actual model input")
    return ModelCallTrace(stage=stage, model=model,
                          instructions_sha256=digest(instructions.encode("utf-8")),
                          input_sha256=digest(input_text.encode("utf-8")),
                          retrieved_buffer_ids=list(retrieved), presented=list(presented))


ACTIVE_RECORDER = ContextVar("source_evidence_recorder", default=None)


class EvidenceRecorder:
    """Capture call inputs before inference, including interrupted/failed calls."""
    def __init__(self, buffer, calls, persist, manifest=None):
        self.buffer, self.calls, self.persist = buffer, calls, persist
        self.retrieved = []
        self.manifest = manifest

    def record_retrieved(self, records):
        if self.manifest is not None and "files" in self.manifest:
            indexed = {item["source"]: item for item in self.manifest["files"]}
            for record in records:
                meta = record["meta"]
                source = indexed.get(meta["source"])
                if source is None or source["sha256"] != meta["sha256"] or source["kind"] != meta.get("kind", meta["source"].split("/", 1)[0]):
                    raise ValueError("Retrieved passage identity/hash differs from the validated manifest")
        ids = [self.buffer.add_passage(record) for record in records]
        self.retrieved = list(dict.fromkeys(self.retrieved + ids))
        return ids

    def start(self, stage, model, instructions, input_text, presented):
        trace = call_trace(self.buffer, stage, model, instructions, input_text, self.retrieved, presented)
        self.calls.append(trace)
        self.persist()
        return trace

    def finish(self, trace, outcome="completed"):
        trace.outcome = outcome
        self.persist()


@contextmanager
def recording(recorder):
    token = ACTIVE_RECORDER.set(recorder)
    try:
        yield recorder
    finally:
        ACTIVE_RECORDER.reset(token)


class EvidenceRun:
    """Unique standalone extraction/answer/evaluation trace with immutable disk snapshots."""
    def __init__(self, state_root: Path, operation: str, manifest=None):
        self.path = Path(state_root) / "evidence_runs" / (operation + "-" + uuid4().hex) / "trace.json"
        self.operation = operation
        self.calls = []
        self.links = []
        self.issues = []
        self.model_outputs = []
        self.publication_status = "not_published"
        self.buffer = SourceBuffer(directory=Path(state_root) / "source_buffer")
        self.recorder = EvidenceRecorder(self.buffer, self.calls, self.save, manifest=manifest)

    def save(self):
        from .report_state import atomic_write

        payload = {"schema_version": 1, "operation": self.operation,
                   "retrieved_buffer_ids": self.recorder.retrieved,
                   "model_calls": [item.model_dump() for item in self.calls],
                   "links": [item.model_dump() for item in self.links], "issues": self.issues,
                   "model_outputs": self.model_outputs, "publication_status": self.publication_status,
                   "source_buffer": {key: passage.model_dump() for key, passage in self.buffer.snapshots.items()}}
        atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))
