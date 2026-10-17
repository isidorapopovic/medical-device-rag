"""Opt-in structural child retrieval with immutable canonical parent citations.

No normative clause inference: boundaries use literal headings/list/paragraph
markers. Existing extracted spans remain the sole citation units.
"""
import copy
import hashlib
import json
import os
import re
import time
from functools import wraps
from uuid import uuid4
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ingestion import IngestionStore, atomic_bytes, confined, records_from_manifest
from .retrieval_safety import RecordCollection
from .runtime import managed_run

VERSION = "structural-child-v1"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def structural_ranges(text: str, target: int = 800) -> list[tuple[int, int]]:
    if not isinstance(text, str) or len(text) > 20000 or not 100 <= target <= 4000:
        raise ValueError("Invalid structural chunk bounds")
    # Never cut a table cell, numbered clause or single long paragraph blindly.
    boundaries = {0, len(text)}
    for match in re.finditer(r"\n\s*\n|(?m:^(?=\s*(?:#{1,6}\s|(?:Article|ANNEX|Section)\b|\d+(?:\.\d+)*[.)]?\s|[-*]\s)))", text):
        boundaries.add(match.start())
    ordered = sorted(boundaries)
    units = []
    for left, right in zip(ordered, ordered[1:]):
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            units.append((left, right))
    # Small contiguous prose paragraphs may share a child, but clause/heading
    # boundaries stay explicit. target is a soft bound for an atomic paragraph.
    result = []
    for left, right in units:
        if result and right - result[-1][0] <= target and not re.match(
                r"(?:#{1,6}\s|Article\b|ANNEX\b|Section\b|\d+[.)\s]|[-*]\s)", text[left:]):
            result[-1] = (result[-1][0], right)
        else:
            result.append((left, right))
    return result


class StructuralSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    version: Literal["structural-child-v1"] = VERSION
    project_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal["legal", "device"]
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_revision: str = Field(max_length=200)
    target: int = Field(ge=100, le=4000)
    manifests: list[str] = Field(min_length=1, max_length=2000)
    parents: list[dict] = Field(max_length=100000)
    children: list[dict] = Field(max_length=100000)

    @model_validator(mode="after")
    def inventory(self):
        if len(set(self.manifests)) != len(self.manifests) or len({r["id"] for r in self.parents}) != len(self.parents):
            raise ValueError("Duplicate manifest or parent identity")
        if len({r["id"] for r in self.children}) != len(self.children):
            raise ValueError("Duplicate child identity")
        parents = {r["id"]: r for r in self.parents}
        for child in self.children:
            meta = child["meta"]
            parent = parents.get(meta["parent_id"])
            if parent is None or parent["text"][meta["child_start"]:meta["child_end"]] != child["text"]:
                raise ValueError("Structural child is not an exact parent slice")
        return self


def retrieval_event(function):
    @wraps(function)
    def logged(self, *args, **kwargs):
        from .telemetry import emit
        from .errors import FoundationError
        started, correlation, error, count = time.perf_counter(), str(uuid4()), None, 0
        try:
            result = function(self, *args, **kwargs)
            count = len(result.get("passages", [])) if isinstance(result, dict) else 0
            return result
        except Exception as exc:
            error = exc.code if isinstance(exc, FoundationError) else "storage_error" if isinstance(exc, OSError) else "validation_error"
            raise
        finally:
            emit(correlation, self.store.project_key, "retrieval",
                 outcome="failed" if error else "completed", error_code=error,
                 elapsed_ms=max(0, int((time.perf_counter()-started)*1000)), source_counts=count)
    return logged


class StructuralIndex:
    def __init__(self, root: Path, source_store: IngestionStore):
        self.store = source_store
        self.directory = confined(root, root / source_store.project_key)
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid structural index identity")
        return confined(self.root, self.directory / (key + ".json"))

    def _snapshot(self, manifests: list[str], kind: str, target: int,
                  model: str, revision: str) -> StructuralSnapshot:
        parents, children, documents = [], [], set()
        for key in sorted(manifests):
            manifest = self.store.load(key)
            self.store.original(manifest)
            doc = manifest.document
            if doc.collection != kind or doc.project_id != self.store.project_id or str(doc.id) in documents:
                raise ValueError("Mixed corpus/project or duplicate document revisions")
            documents.add(str(doc.id))
            if manifest.extraction.status not in {"parsed", "partial"}:
                raise ValueError("Source has no usable extraction")
            for parent in records_from_manifest(manifest, key):
                parents.append(parent)
                unit = manifest.extraction.units[manifest.span_units[parent["meta"]["source_span_id"]] - 1]
                for left, right in structural_ranges(parent["text"], target):
                    child = copy.deepcopy(parent)
                    child["text"] = parent["text"][left:right]
                    child["id"] = "CH-" + digest([VERSION, parent["id"], parent["meta"], left, right, child["text"]])
                    child["meta"].update(parent_id=parent["id"], parent_span_id=parent["meta"]["source_span_id"],
                        child_start=left, child_end=right, section_path=json.dumps(unit.sections, ensure_ascii=False),
                        structural_version=VERSION, atomic_oversize=right-left > target)
                    children.append(child)
        return StructuralSnapshot(project_key=self.store.project_key, kind=kind, embedding_model=model,
            embedding_revision=revision, target=target, manifests=sorted(manifests), parents=parents, children=children)

    @managed_run
    @retrieval_event
    def build(self, manifests: list[str], kind: str, *, target: int = 800,
              dense: bool = False) -> str:
        if type(dense) is not bool or kind not in {"legal", "device"}:
            raise ValueError("Invalid structural index options")
        if not isinstance(manifests, list) or not manifests or len(manifests) > 2000 or len(set(manifests)) != len(manifests):
            raise ValueError("Supply distinct source manifests")
        model, revision = os.getenv("EMBEDDING_MODEL", "embeddinggemma"), os.getenv("EMBEDDING_REVISION", "")
        snapshot = self._snapshot(manifests, kind, target, model, revision)
        payload = snapshot.model_dump()
        key = digest(payload)
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        if len(serialized) > 50 * 1024 * 1024:
            raise ValueError("Structural index size exceeds limit")
        # Build all embeddings before publishing either snapshot or named index.
        # Dense collections are immutable and isolated from the legacy collection.
        if dense:
            from . import search
            vectors = []
            for begin in range(0, len(snapshot.children), 32):
                batch = snapshot.children[begin:begin+32]
                embeddings = search.embeddings([r["text"] for r in batch])
                if len(embeddings) != len(batch):
                    raise ValueError("Structural embedding count mismatch")
                vectors.extend(embeddings)
            import chromadb
            db = chromadb.PersistentClient(path=str(self.directory / "vectors"),
                settings=chromadb.config.Settings(anonymized_telemetry=False))
            name = "s6_" + key
            if name not in [getattr(c, "name", c) for c in db.list_collections()]:
                c = db.create_collection(name=name, embedding_function=None,
                    metadata={"embedding_model": model, "embedding_revision": revision, "project_key": self.store.project_key})
                try:
                    for begin in range(0, len(snapshot.children), 32):
                        batch = snapshot.children[begin:begin+32]
                        c.add(ids=[r["id"] for r in batch], documents=[r["text"] for r in batch],
                              metadatas=[r["meta"] for r in batch], embeddings=vectors[begin:begin+len(batch)])
                except BaseException:
                    db.delete_collection(name)
                    raise
        atomic_bytes(self._path(key), serialized, immutable=True)
        return key

    def load(self, key: str, *, documents_root: Path | None = None) -> StructuralSnapshot:
        path = self._path(key)
        if path.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("Structural index size exceeds limit")
        data = json.loads(path.read_text(encoding="utf-8"))
        if digest(data) != key:
            raise ValueError("Structural index hash mismatch")
        snapshot = StructuralSnapshot.model_validate(data)
        expected = self._snapshot(snapshot.manifests, snapshot.kind, snapshot.target,
                                  snapshot.embedding_model, snapshot.embedding_revision)
        if expected != snapshot:
            raise ValueError("Structural snapshot provenance mismatch")
        if documents_root is not None:
            from .core import resolve_source
            checked = set()
            for parent in snapshot.parents:
                if parent["meta"]["source"] in checked:
                    continue
                checked.add(parent["meta"]["source"])
                source = resolve_source(parent["meta"]["source"], documents_root)
                if hashlib.sha256(source.read_bytes()).hexdigest() != parent["meta"]["sha256"]:
                    raise ValueError("Structural source changed; build a new snapshot")
        return snapshot

    @managed_run
    @retrieval_event
    def retrieve(self, key: str, queries: list[str], *, mode: str = "bm25", k: int = 7,
                 backend: str = "none", documents_root: Path | None = None) -> dict:
        from . import search
        if type(k) is not int or not 1 <= k <= 30 or mode not in {"bm25", "dense", "hybrid"}:
            raise ValueError("Invalid structural retrieval budget/mode")
        if backend not in {"none", "llm", "cross_encoder"}:
            raise ValueError("Invalid structural reranker")
        snapshot = self.load(key, documents_root=documents_root)
        rows = RecordCollection(snapshot.children)
        fallbacks = []
        if mode in {"dense", "hybrid"}:
            if (snapshot.embedding_model, snapshot.embedding_revision) != (
                    os.getenv("EMBEDDING_MODEL", "embeddinggemma"), os.getenv("EMBEDDING_REVISION", "")):
                fallbacks.append("embedding_identity_mismatch")
            else:
                try:
                    if not (self.directory / "vectors").is_dir():
                        raise FileNotFoundError("No dense structural index")
                    import chromadb
                    rows = chromadb.PersistentClient(path=str(self.directory / "vectors"),
                        settings=chromadb.config.Settings(anonymized_telemetry=False)).get_collection(
                        name="s6_" + key, embedding_function=None)
                except Exception as exc:
                    from .retrieval_safety import recoverable
                    # A deliberately BM25-only snapshot has no dense collection.
                    if not recoverable(exc, storage=True):
                        raise
                    fallbacks.append("dense_index_unavailable")
        effective = "bm25" if fallbacks else mode
        # Retrieve/rerank canonical parents, not child fragments; child matches
        # only nominate their exact immutable parent citation units.
        result = search.retrieve_candidates(queries, snapshot.kind, k=30, mode=effective, rerank=False,
            corpus_override=rows, expected_records=snapshot.children, resilient=True, diagnostics=True,
            manifest_fingerprint=key, record_results=False)
        parents = {p["id"]: p for p in snapshot.parents}
        selected, seen, mapping = [], set(), {}
        for child in result["passages"]:
            parent_id = child["meta"]["parent_id"]
            mapping[child["id"]] = parent_id
            if parent_id not in seen:
                selected.append(copy.deepcopy(parents[parent_id]))
                seen.add(parent_id)
        rerank_fallback = []
        rerank_diagnostics = None
        reranked = False
        if backend != "none" and selected:
            try:
                from .reranking import capture_scores
                with capture_scores(backend) as captured:
                    selected = search.rerank_passages(queries[0], selected[:30], backend=backend)
                rerank_diagnostics = captured[-1] if captured else None
                reranked = True
            except Exception as exc:
                from .retrieval_safety import recoverable
                if not recoverable(exc):
                    raise
                rerank_fallback.append("reranker_unavailable_fusion_preserved")
        from .source_buffer import ACTIVE_RECORDER
        recorder = ACTIVE_RECORDER.get()
        if recorder is not None:
            recorder.record_retrieved(selected[:k])
        result["passages"] = selected[:k]
        result["structural"] = {"snapshot": key, "version": VERSION, "child_to_parent": mapping,
            "parent_ids": [p["id"] for p in selected[:k]], "reranked": reranked,
            "reranker": rerank_diagnostics, "evidence_status": "not_assessed" if selected else "INSUFFICIENT_EVIDENCE"}
        result["diagnostics"]["fallback_codes"] += fallbacks + rerank_fallback
        return result
