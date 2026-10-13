"""Local reranker selection, scored copies and exact tokenizer-input diagnostics."""
import copy
import hashlib
import inspect
import json
import math
import os
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

MODEL = "BAAI/bge-reranker-base"
REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"
PREPROCESSING = "fast-offsets-query-prefix128-only-second-right-truncation-v1"
_SCORERS = {}
_LOAD_LOCK = threading.Lock()
_OUTPUT = ContextVar("reranker_output", default=None)
_SELECTED = ContextVar("selected_reranker", default=None)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def backend_selection(backend=None, rerank=None):
    """Explicit backend, explicit legacy bool, environment backend, legacy flag."""
    if backend is None and rerank is not None:
        backend = "llm" if rerank else "none"
    if backend is None:
        backend = os.getenv("RERANK_BACKEND", "").strip().lower()
        if not backend:
            enabled = os.getenv("RERANK_ENABLED", "false").lower()
            if enabled not in {"true", "false"}:
                raise ValueError("RERANK_ENABLED must be 'true' or 'false'")
            backend = "llm" if enabled == "true" else "none"
    if backend not in {"none", "llm", "cross_encoder"}:
        raise ValueError("RERANK_BACKEND must be none, llm, or cross_encoder")
    return backend


def cross_encoder_settings():
    model = os.getenv("CROSS_ENCODER_MODEL", MODEL).strip()
    revision = os.getenv("CROSS_ENCODER_REVISION", REVISION if model == MODEL else "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", model):
        raise ValueError("CROSS_ENCODER_MODEL must be a Hugging Face namespace/model ID")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("CROSS_ENCODER_MODEL requires a pinned 40-character CROSS_ENCODER_REVISION commit")
    settings = {"model": model, "revision": revision, "device": "cpu", "dtype": "float32",
                "preprocessing": PREPROCESSING, "score_transformation": "identity_raw_logit",
                "local_files_only": True, "query_token_limit": 128, "cpu_threads": 4,
                "attention_implementation": "eager"}
    for key, default, upper, lower in (("CROSS_ENCODER_MAX_TOKENS", 512, 512, 32),
                                      ("CROSS_ENCODER_BATCH_SIZE", 4, 4, 1)):
        try:
            number = int(os.getenv(key, str(default)))
        except ValueError:
            raise ValueError(f"{key} must be an integer between {lower} and {upper}") from None
        if not lower <= number <= upper:
            raise ValueError(f"{key} must be between {lower} and {upper}")
        settings["max_tokens" if key.endswith("TOKENS") else "batch_size"] = number
    return settings


def cache_folder():
    return Path(os.getenv("CROSS_ENCODER_CACHE", str(Path(__file__).resolve().parent.parent / "reports" / "reranker-cache")))


def provisioned_folder(settings):
    return cache_folder() / "provisioned" / settings["model"].replace("/", "--") / settings["revision"]


def library_versions():
    result = {}
    for package in ("sentence-transformers", "transformers", "torch", "tokenizers", "safetensors"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "unavailable"
    return result


def local_snapshot(settings):
    provisioned = provisioned_folder(settings)
    marker = provisioned / "provision.json"
    if marker.is_file():
        try:
            if json.loads(marker.read_text()) != {"model": settings["model"], "revision": settings["revision"]}:
                raise RuntimeError("Cross-encoder provisioning identity mismatch; verify the pinned model before retrying")
            return provisioned
        except (OSError, ValueError):
            raise RuntimeError("Invalid cross-encoder provisioning marker; verify the cached model before retrying") from None
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("Cross-encoder dependencies unavailable. Install requirements-rerank.txt; no backend was substituted.") from exc
    try:
        return Path(snapshot_download(settings["model"], revision=settings["revision"],
                                      cache_dir=str(cache_folder()), local_files_only=True, token=False))
    except Exception as exc:
        raise RuntimeError("Pinned cross-encoder model is not cached. Download the documented revision explicitly into CROSS_ENCODER_CACHE, then retry; no backend was substituted.") from exc


@lru_cache(maxsize=4)
def _artifact_hashes(files):
    result = {}
    for name, path, _, _ in files:
        hasher = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        result[name] = hasher.hexdigest()
    return result


def reranker_identity(backend):
    if backend == "none":
        return {"backend": "none"}
    if backend == "llm":
        from .config import ollama_num_ctx
        return {"backend": "llm", "model": os.getenv("OLLAMA_LLM_MODEL", "qwen3:4b"),
                "num_ctx": ollama_num_ctx(), "score_transformation": "llm_relevance_0_100",
                "token_visibility": "unverified", "preprocessing": "full-candidate-text-v1"}
    settings = cross_encoder_settings()
    libraries = library_versions()
    if any(libraries[name] == "unavailable" for name in ("sentence-transformers", "torch", "transformers")):
        raise RuntimeError("Cross-encoder dependencies unavailable. Install requirements-rerank.txt; no backend was substituted.")
    snapshot = local_snapshot(settings)
    # Fingerprint both weights and tokenizer/config, rather than trusting a tag.
    names = ("model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json",
             "special_tokens_map.json", "sentencepiece.bpe.model")
    files = []
    for name in names:
        path = snapshot / name
        if not path.is_file():
            raise RuntimeError(f"Pinned cross-encoder snapshot is incomplete: missing {name}; download the documented files explicitly.")
        stat = path.stat()
        files.append((name, str(path), stat.st_size, stat.st_mtime_ns))
    identity = {"backend": "cross_encoder", **settings, "libraries": libraries,
                "artifacts_sha256": copy.deepcopy(_artifact_hashes(tuple(files))),
                "implementation_sha256": digest(inspect.getsource(CrossEncoderScorer))}
    identity["fingerprint"] = digest(identity)
    return identity


class CrossEncoderScorer:
    """Use CrossEncoder's loaded model with the exact offset-traced token IDs.

    Scoring pretokenized tensors avoids a second, potentially different truncation
    inside predict(). No network operation or document transmission occurs here.
    """
    def __init__(self, identity):
        try:
            import torch
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("Cross-encoder dependencies unavailable or incompatible. Install requirements-rerank.txt; no backend was substituted.") from exc
        self.torch, self.identity = torch, copy.deepcopy(identity)
        try:
            torch.set_num_threads(identity["cpu_threads"])
            self.encoder = CrossEncoder(str(local_snapshot(identity)), device="cpu", max_length=identity["max_tokens"],
                local_files_only=True, trust_remote_code=False, token=False,
                model_kwargs={"torch_dtype": torch.float32, "attn_implementation": "eager"},
                tokenizer_kwargs={"use_fast": True})
            self.encoder.model.to(device="cpu", dtype=torch.float32)
            self.encoder.model.eval()
            self.tokenizer = self.encoder.tokenizer
            self.tokenizer.truncation_side = "right"
            if not self.tokenizer.is_fast or self.encoder.config.num_labels != 1:
                raise ValueError("Requires a fast offset tokenizer and one output logit")
            positions = self.encoder.config.max_position_embeddings
            limit = positions - 2 if self.encoder.config.model_type == "xlm-roberta" else positions
            if identity["max_tokens"] > limit:
                raise ValueError("Token limit exceeds model position capacity")
        except Exception as exc:
            raise RuntimeError("Pinned local cross-encoder could not load on CPU float32. Check optional versions and cached files; no backend was substituted.") from exc

    def prepare(self, query, passage):
        specials = self.tokenizer.num_special_tokens_to_add(pair=True)
        budget = min(128, self.identity["max_tokens"] - specials - 1)
        query_tokens = self.tokenizer(query, add_special_tokens=False, return_offsets_mapping=True,
                                      truncation=True, max_length=budget)
        offsets = query_tokens["offset_mapping"]
        if not offsets:
            raise ValueError("Rerank query has no tokens")
        query_end = max(end for start, end in offsets)
        retained_query = query[:query_end]
        pair = self.tokenizer(retained_query, passage["text"], truncation="only_second",
            max_length=self.identity["max_tokens"], return_offsets_mapping=True)
        doc_offsets = [(start, end) for seq, (start, end) in zip(pair.sequence_ids(), pair["offset_mapping"])
                       if seq == 1 and end > start]
        if not doc_offsets:
            raise ValueError("Candidate has no document tokens within the pair budget")
        start, end = min(s for s, e in doc_offsets), max(e for s, e in doc_offsets)
        features = {key: value for key, value in pair.items() if key != "offset_mapping"}
        return {"id": passage["id"], "features": features,
                "coverage": {"start": start, "end": end, "query_start": 0, "query_end": query_end,
                    "passage_truncated": end < len(passage["text"].rstrip()),
                    "query_truncated": query_end < len(query.rstrip()), "token_count": len(pair["input_ids"]),
                    "encoded_sha256": digest(features), "visibility": "token_offset_envelope"}}

    def score(self, prepared, batch_size):
        result = []
        with self.torch.inference_mode():
            for begin in range(0, len(prepared), batch_size):
                batch = prepared[begin:begin + batch_size]
                features = self.tokenizer.pad([p["features"] for p in batch], padding=True, return_tensors="pt")
                features = {key: value.to("cpu") for key, value in features.items()}
                logits = self.encoder.model(**features, return_dict=True).logits
                if tuple(logits.shape) != (len(batch), 1):
                    raise ValueError("Cross-encoder must return one scalar per candidate")
                result.extend({"id": p["id"], "score": float(value)}
                              for p, value in zip(batch, logits[:, 0].cpu().tolist()))
        return result


def get_scorer(identity):
    with _LOAD_LOCK:
        key = identity["fingerprint"]
        if key not in _SCORERS:
            _SCORERS[key] = CrossEncoderScorer(identity)
        return _SCORERS[key]


def scored_copies(passages, scores):
    ids = [p["id"] for p in passages]
    returned = [s["id"] for s in scores]
    if len(ids) != len(set(ids)) or len(returned) != len(set(returned)) or set(ids) != set(returned):
        raise ValueError("Reranker requires a one-to-one candidate/score mapping; no backend was substituted")
    values = {}
    for item in scores:
        value = item["score"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Reranker scores must be finite scalars; no backend was substituted")
        values[item["id"]] = float(value)
    order = {key: i for i, key in enumerate(ids)}
    return sorted(copy.deepcopy(passages), key=lambda p: (-values[p["id"]], order[p["id"]]))


def publish(diagnostics):
    sink = _OUTPUT.get()
    if sink is not None:
        sink.append(diagnostics)


def active_backend():
    return _SELECTED.get()


@contextmanager
def capture_scores(backend=None):
    result = []
    selected_token = _SELECTED.set(backend)
    token = _OUTPUT.set(result)
    try:
        yield result
    finally:
        _OUTPUT.reset(token)
        _SELECTED.reset(selected_token)


def rerank_candidates(query, passages, *, backend=None, scorer=None, identity=None):
    backend = backend_selection(backend)
    if len(passages) > 30:
        raise ValueError("Rerank at most 30 candidate pairs")
    if not query.strip():
        raise ValueError("Rerank query must not be empty")
    if len({p["id"] for p in passages}) != len(passages):
        raise ValueError("Reranker candidates must have unique IDs")
    if backend == "none" or not passages:
        return {"passages": copy.deepcopy(passages), "diagnostics": {"backend": backend, "scores": []}}
    if backend == "llm":
        from .search import _llm_rerank
        return _llm_rerank(query, passages)
    identity = identity or reranker_identity(backend)
    scorer = scorer or get_scorer(identity)
    prepared = [scorer.prepare(query, passage) for passage in passages]
    if [p["id"] for p in prepared] != [p["id"] for p in passages]:
        raise ValueError("Prepared pairs must retain original candidate identity")
    from .source_buffer import ACTIVE_RECORDER
    recorder, trace = ACTIVE_RECORDER.get(), None
    diagnostics = {"backend": backend, "identity": identity, "query": query, "query_sha256": digest(query),
                   "batch_size": identity["batch_size"], "max_tokens": identity["max_tokens"], "scores": []}
    for pair, passage in zip(prepared, passages):
        coverage = pair["coverage"]
        if not 0 <= coverage["start"] < coverage["end"] <= len(passage["text"]):
            raise ValueError("Reranker token offsets are outside the original passage")
        if not 0 < coverage["token_count"] <= identity["max_tokens"]:
            raise ValueError("Reranker token budget exceeded")
    if recorder is not None:
        ids = recorder.record_retrieved(passages)
        presented = [recorder.buffer.presented(key, p["coverage"]["start"], p["coverage"]["end"])
                     for key, p in zip(ids, prepared)]
        actual_input = "\n\n".join(f"{p['id']}\nQUERY: {query[:pair['coverage']['query_end']]}\nTEXT: {p['text'][pair['coverage']['start']:pair['coverage']['end']]}\nENCODED: {pair['coverage']['encoded_sha256']}"
                                     for p, pair in zip(passages, prepared))
        trace = recorder.start("cross_encoder_rerank", identity["model"], json.dumps(identity, sort_keys=True), actual_input, presented)
        trace.rerank = {**diagnostics, "inputs": [{"id": p["id"], **p["coverage"]} for p in prepared]}
        recorder.persist()
    begin = time.perf_counter()
    try:
        scores = scorer.score(prepared, identity["batch_size"])
        ranked = scored_copies(passages, scores)
        by_id = {s["id"]: s["score"] for s in scores}
        diagnostics["scores"] = [{"id": p["id"], "score": float(by_id[p["id"]]), **p["coverage"]} for p in prepared]
        diagnostics["elapsed_seconds"] = time.perf_counter() - begin
    except Exception:
        if trace is not None:
            recorder.finish(trace, "failed")
        raise
    if trace is not None:
        trace.rerank = diagnostics
        recorder.finish(trace)
    publish(diagnostics)
    return {"passages": ranked, "diagnostics": diagnostics}


def requirement_rerank_query(original, profile):
    # Profile facts remain explicitly unverified; no expansion query contributes
    # an independent score or speculative applicability assumption.
    facts = {key: profile[key] for key in ("device_name", "intended_purpose") if profile.get(key)}
    return original + ("\nUNVERIFIED APPLICABILITY QUALIFIERS: " + json.dumps(facts, ensure_ascii=False) if facts else "")


def citation_rerank_coverage(links, retrieval_trace):
    diagnostics = (retrieval_trace or {}).get("reranker") or {}
    scores = {s["id"]: s for s in diagnostics.get("scores", [])}
    result = []
    for link in links:
        score = scores.get(link.chunk_id)
        seen, reason = None, "not_reranked"
        if score is not None and diagnostics.get("backend") == "cross_encoder":
            seen = score["start"] <= link.start < link.end <= score["end"]
            reason = "within_token_offset_envelope" if seen else "outside_reranker_token_range"
        elif score is not None:
            reason = "llm_token_visibility_unverified"
        result.append({"claim_id": link.claim_id, "buffer_id": link.buffer_id, "chunk_id": link.chunk_id,
                       "start": link.start, "end": link.end, "reranker_seen": seen, "reason": reason})
    return result
