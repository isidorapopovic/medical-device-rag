import copy
import json
import math
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mdr_rag import reranking, search, pipeline, review_state
from mdr_rag.source_buffer import EvidenceRun, recording
from test_report_state import workflow
from test_query_retrieval import corpus


def candidates():
    return [{"id": f"D-{n}", "text": "Synthetic maintenance records. Unseen tail.",
             "meta": {"source": "device/records.txt", "kind": "device", "sha256": "device-hash", "page": 0, "block": n}}
            for n in (1, 2, 3)]


def identity():
    return {"backend": "cross_encoder", **reranking.cross_encoder_settings(), "fingerprint": "fake-test-model",
            "libraries": {"sentence-transformers": "fake"}, "artifacts_sha256": {"model": "fake"}}


class FakeScorer:
    def __init__(self, scores=None):
        self.scores = scores
        self.calls = []
    def prepare(self, query, passage):
        return {"id": passage["id"], "features": {"input_ids": [1, 2]}, "coverage": {
            "start": 0, "end": 29, "query_start": 0, "query_end": len(query),
            "passage_truncated": True, "query_truncated": False, "token_count": 2,
            "encoded_sha256": reranking.digest([1, 2]), "visibility": "token_offset_envelope"}}
    def score(self, pairs, batch_size):
        self.calls.append((pairs, batch_size))
        return self.scores if self.scores is not None else [{"id": p["id"], "score": 2.0 if p["id"] == "D-2" else 1.0} for p in pairs]


def test_stable_scored_copies_preserve_identity_text_and_hashes():
    original = candidates()
    original[0]["provenance"] = {"query": "source query"}
    before = copy.deepcopy(original)
    result = reranking.rerank_candidates("original", original, backend="cross_encoder", scorer=FakeScorer(), identity=identity())
    assert [p["id"] for p in result["passages"]] == ["D-2", "D-1", "D-3"]
    assert original == before
    assert sorted(result["passages"], key=lambda p: p["id"]) == original
    assert all(p is not q for p in result["passages"] for q in original)
    assert result["diagnostics"]["scores"][0]["passage_truncated"]
    assert all(s["end"] == 29 for s in result["diagnostics"]["scores"])
    result["passages"][1]["meta"]["sha256"] = "mutated-copy"
    assert original == before


@pytest.mark.parametrize("scores", [[{"id": "D-1", "score": float("nan")}, {"id": "D-2", "score": 1}, {"id": "D-3", "score": 1}],
                                    [{"id": "D-1", "score": float("inf")}, {"id": "D-2", "score": 1}, {"id": "D-3", "score": 1}],
                                    [{"id": "D-1", "score": 1}],
                                    [{"id": "D-1", "score": 1}, {"id": "D-1", "score": 2}, {"id": "D-3", "score": 1}],
                                    [{"id": "invented", "score": 1}, {"id": "D-2", "score": 1}, {"id": "D-3", "score": 1}]])
def test_invalid_scores_rejected_without_backend_switch(scores, monkeypatch):
    monkeypatch.setattr(search, "_llm_rerank", lambda *args: pytest.fail("Silent LLM fallback"))
    with pytest.raises(ValueError, match="finite|one-to-one"):
        reranking.rerank_candidates("original", candidates(), backend="cross_encoder", scorer=FakeScorer(scores), identity=identity())


def test_unavailable_dependency_is_actionable(monkeypatch):
    monkeypatch.setattr(reranking, "library_versions", lambda: {"sentence-transformers": "unavailable", "torch": "unavailable", "transformers": "unavailable"})
    with pytest.raises(RuntimeError, match="Install requirements-rerank.txt; no backend was substituted"):
        reranking.rerank_candidates("original", candidates(), backend="cross_encoder")


def test_missing_download_is_explicit_and_local_only(monkeypatch, tmp_path):
    monkeypatch.setattr(reranking, "cache_folder", lambda: tmp_path / "missing")
    seen = []
    def missing(*args, **kwargs):
        seen.append(kwargs)
        raise FileNotFoundError("not cached")
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=missing))
    with pytest.raises(RuntimeError, match="not cached.*explicitly"):
        reranking.local_snapshot(reranking.cross_encoder_settings())
    assert seen[0]["local_files_only"] is True and seen[0]["token"] is False
    assert seen[0]["revision"] == reranking.REVISION


def test_no_cloud_or_ollama_calls(monkeypatch):
    import ollama
    def forbidden(*args, **kwargs):
        pytest.fail("Network or Ollama call during fake CPU reranking")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(ollama, "chat", forbidden)
    monkeypatch.setattr(ollama, "embed", forbidden)
    result = reranking.rerank_candidates("original", candidates(), backend="cross_encoder", scorer=FakeScorer(), identity=identity())
    assert len(result["passages"]) == 3


def test_lazy_load_once_per_fingerprint(monkeypatch):
    reranking._SCORERS.clear()
    constructions = []
    monkeypatch.setattr(reranking, "CrossEncoderScorer", lambda info: constructions.append(info) or FakeScorer())
    first = reranking.get_scorer(identity())
    assert reranking.get_scorer(identity()) is first
    assert len(constructions) == 1
    reranking._SCORERS.clear()


def test_none_backend_copies_without_loading(monkeypatch):
    monkeypatch.setattr(reranking, "get_scorer", lambda *args: pytest.fail("none loaded a model"))
    original = candidates()
    result = reranking.rerank_candidates("original", original, backend="none")
    assert result["passages"] == original and result["passages"][0] is not original[0]
    assert result["diagnostics"] == {"backend": "none", "scores": []}


def test_llm_backend_remains_selectable_and_saves_scores(monkeypatch):
    import ollama
    monkeypatch.setattr(ollama, "chat", lambda **kwargs: {"message": {"content": json.dumps({"scores": [
        {"source_id": p["id"], "score": 80} for p in candidates()]})}})
    result = reranking.rerank_candidates("original", candidates(), backend="llm")
    assert [p["id"] for p in result["passages"]] == ["D-1", "D-2", "D-3"]
    assert [s["score"] for s in result["diagnostics"]["scores"]] == [80, 80, 80]
    assert result["diagnostics"]["identity"]["token_visibility"] == "unverified"


def test_token_ranges_are_saved_separately_from_full_chunk(tmp_path):
    run = EvidenceRun(tmp_path, "fake-rerank")
    with recording(run.recorder):
        result = reranking.rerank_candidates("original", candidates(), backend="cross_encoder", scorer=FakeScorer(), identity=identity())
    trace = run.recorder.calls[0]
    assert trace.outcome == "completed" and trace.rerank["scores"]
    assert all(p.end == 29 for p in trace.presented)
    assert all(len(run.buffer.get_passage(p.buffer_id).text) > p.end for p in trace.presented)
    assert result["diagnostics"]["identity"]["device"] == "cpu"


def test_failed_scoring_trace_remains_failed(tmp_path):
    run = EvidenceRun(tmp_path, "fake-rerank")
    with recording(run.recorder), pytest.raises(ValueError):
        reranking.rerank_candidates("original", candidates(), backend="cross_encoder", scorer=FakeScorer([]), identity=identity())
    trace = run.recorder.calls[0]
    assert trace.outcome == "failed" and trace.rerank["inputs"]


@pytest.mark.parametrize("name,value", [("CROSS_ENCODER_MAX_TOKENS", "513"), ("CROSS_ENCODER_MAX_TOKENS", "bad"),
                                        ("CROSS_ENCODER_BATCH_SIZE", "5"), ("CROSS_ENCODER_REVISION", "main")])
def test_invalid_cross_encoder_configuration(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        reranking.cross_encoder_settings()


def test_rerank_budget_is_bounded():
    with pytest.raises(ValueError, match="at most 30"):
        reranking.rerank_candidates("original", candidates() * 11, backend="cross_encoder", scorer=FakeScorer(), identity=identity())


def test_backend_precedence_and_legacy_flag(monkeypatch):
    monkeypatch.setenv("RERANK_BACKEND", "cross_encoder")
    assert reranking.backend_selection() == "cross_encoder"
    assert reranking.backend_selection(rerank=True) == "llm"
    assert reranking.backend_selection(rerank=False) == "none"
    assert reranking.backend_selection("none", True) == "none"
    monkeypatch.delenv("RERANK_BACKEND")
    monkeypatch.setenv("RERANK_ENABLED", "true")
    assert reranking.backend_selection() == "llm"


@pytest.mark.parametrize("backend", ["none", "llm", "cross_encoder"])
def test_cli_explicit_backend(monkeypatch, backend):
    import main
    monkeypatch.delenv("RERANK_BACKEND", raising=False)
    monkeypatch.delenv("RERANK_ENABLED", raising=False)
    monkeypatch.setattr(sys, "argv", ["main.py", "--rerank-backend", backend, "ask", "synthetic"])
    seen = []
    monkeypatch.setattr(main, "run_ask", lambda query: seen.append(reranking.backend_selection()))
    assert main.main() == 0 and seen == [backend]


def test_review_scores_original_plus_profile_preserves_candidate_provenance(workflow, corpus, monkeypatch):
    monkeypatch.setenv("MULTI_QUERY_ENABLED", "true")
    monkeypatch.setenv("RERANK_BACKEND", "cross_encoder")
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    corpus[0][0]["id"], corpus[0][0]["text"] = "D-1", "Synthetic maintenance records. Unseen tail."
    workflow["profile"]["intended_purpose"] = "Explicit supplied use"
    monkeypatch.setattr(reranking, "reranker_identity", lambda backend: identity())
    monkeypatch.setattr(review_state, "reranker_identity", lambda backend: identity())
    fake = FakeScorer()
    monkeypatch.setattr(reranking, "get_scorer", lambda info: fake)
    state = pipeline.run_review(assessment_id="demo", limit=1)
    section = state.sections["R1"]
    diagnostics = section.retrieval_trace["reranker"]
    assert diagnostics["query"].startswith(section.queries[0])
    assert "Explicit supplied use" in diagnostics["query"]
    assert "process test evidence" not in diagnostics["query"]
    assert len(fake.calls) == 1 and fake.calls[0][1] == 4
    assert all(c["provenance"] for c in section.retrieval_trace["candidates"])
    assert section.finding_history[-1]["retrieval_trace"]["reranker"] == diagnostics
    trace = next(call for call in section.model_calls if call.stage == "cross_encoder_rerank")
    assert trace.rerank["identity"]["fingerprint"] == "fake-test-model"


def test_cross_encoder_identity_invalidates_retrieval_not_queries(workflow):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    changed = dict(state.config, reranker_backend="cross_encoder", reranker_identity=identity())
    section = state.sections["R1"].model_copy(deep=True)
    from mdr_rag.report_state import invalidate
    deps = review_state.dependencies(section.requirement, state.device_profile, state.corpus_fingerprint, changed)
    assert invalidate(section, deps)
    assert section.checkpoint == "queries" and section.query_plan is not None


def test_tokenization_offsets_and_both_truncations():
    import re
    class Encoding(dict):
        def sequence_ids(self):
            return self.sequences
    class Tokenizer:
        def num_special_tokens_to_add(self, pair):
            return 4
        def __call__(self, query, document=None, **kwargs):
            query_offsets = [(m.start(), m.end()) for m in re.finditer(r"\S+", query)]
            if document is None:
                retained = query_offsets[:kwargs["max_length"]]
                return {"input_ids": list(range(len(retained))), "offset_mapping": retained}
            assert kwargs["truncation"] == "only_second"
            doc_offsets = [(m.start(), m.end()) for m in re.finditer(r"\S+", document)]
            doc_offsets = doc_offsets[:kwargs["max_length"] - 4 - len(query_offsets)]
            offsets = [(0, 0)] + query_offsets + [(0, 0)] * 2 + doc_offsets + [(0, 0)]
            result = Encoding(input_ids=list(range(len(offsets))), attention_mask=[1] * len(offsets), offset_mapping=offsets)
            result.sequences = [None] + [0] * len(query_offsets) + [None] * 2 + [1] * len(doc_offsets) + [None]
            return result
    scorer = object.__new__(reranking.CrossEncoderScorer)
    scorer.identity, scorer.tokenizer = dict(identity(), max_tokens=32), Tokenizer()
    passage = {"id": "D-1", "text": "first second third fourth"}
    result = scorer.prepare("word " * 150, passage)
    assert result["coverage"]["passage_truncated"] and result["coverage"]["query_truncated"]
    assert passage["text"][result["coverage"]["start"]:result["coverage"]["end"]] == "first"
    assert result["coverage"]["token_count"] == 32


def test_citation_outside_reranker_input_is_not_marked_scored():
    links = [SimpleNamespace(claim_id="C1", buffer_id="SB", chunk_id="D-1", start=0, end=5),
             SimpleNamespace(claim_id="C2", buffer_id="SB", chunk_id="D-1", start=30, end=40)]
    trace = {"reranker": {"backend": "cross_encoder", "scores": [{"id": "D-1", "start": 0, "end": 29}]}}
    result = reranking.citation_rerank_coverage(links, trace)
    assert result[0]["reranker_seen"] is True
    assert result[1]["reranker_seen"] is False
    assert result[1]["reason"] == "outside_reranker_token_range"
    trace["reranker"]["backend"] = "llm"
    assert reranking.citation_rerank_coverage(links, trace)[0]["reranker_seen"] is None


def test_model_and_library_fingerprints_change(tmp_path, monkeypatch):
    names = ("model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "sentencepiece.bpe.model")
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    libs = {"sentence-transformers": "5.1.2", "transformers": "4.57.1", "torch": "2.8.0"}
    monkeypatch.setattr(reranking, "library_versions", lambda: dict(libs))
    monkeypatch.setattr(reranking, "local_snapshot", lambda settings: tmp_path)
    first = reranking.reranker_identity("cross_encoder")
    (tmp_path / "model.safetensors").write_bytes(b"changed weights")
    second = reranking.reranker_identity("cross_encoder")
    assert second["fingerprint"] != first["fingerprint"]
    assert second["artifacts_sha256"]["model.safetensors"] != first["artifacts_sha256"]["model.safetensors"]
    libs["torch"] = "different-library"
    assert reranking.reranker_identity("cross_encoder")["fingerprint"] != second["fingerprint"]


def test_help_without_optional_imports():
    import subprocess
    script = """
import sys, runpy, importlib.abc
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'sentence_transformers', 'torch'}:
            raise ModuleNotFoundError('Optional dependency deliberately unavailable')
sys.meta_path.insert(0, BlockOptional())
sys.argv = ['main.py', '--help']
runpy.run_path('main.py', run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and "--rerank-backend" in result.stdout


def test_legacy_flag_overrides_cross_encoder_environment(monkeypatch):
    import main
    monkeypatch.setenv("RERANK_BACKEND", "cross_encoder")
    monkeypatch.setenv("RERANK_ENABLED", "false")
    monkeypatch.setattr(sys, "argv", ["main.py", "--rerank", "ask", "synthetic"])
    received = []
    monkeypatch.setattr(main, "run_ask", lambda query: received.append(reranking.backend_selection()))
    assert main.main() == 0 and received == ["llm"]


def test_explicit_provisioning_uses_separate_plain_file_folder(tmp_path, monkeypatch):
    from mdr_rag import download_reranker
    monkeypatch.setattr(reranking, "cache_folder", lambda: tmp_path)
    seen = []
    def download(repo, **kwargs):
        seen.append((repo, kwargs))
        Path(kwargs["local_dir"]).mkdir(parents=True)
        return kwargs["local_dir"]
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    path = Path(download_reranker.download())
    assert "provisioned" in path.parts and "snapshots" not in path.parts
    assert seen[0][1]["revision"] == reranking.REVISION
    assert seen[0][1]["token"] is False and seen[0][1]["max_workers"] == 1
    assert reranking.local_snapshot(reranking.cross_encoder_settings()) == path


def test_provisioning_identity_mismatch_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(reranking, "cache_folder", lambda: tmp_path)
    folder = reranking.provisioned_folder(reranking.cross_encoder_settings())
    folder.mkdir(parents=True)
    marker = folder / "provision.json"
    marker.write_text(json.dumps({"model": "wrong", "revision": "wrong"}))
    original = marker.read_bytes()
    with pytest.raises(RuntimeError, match="identity mismatch"):
        reranking.local_snapshot(reranking.cross_encoder_settings())
    assert marker.read_bytes() == original


@pytest.mark.real_model
@pytest.mark.skipif(os.getenv("RUN_CROSS_ENCODER_SMOKE") != "true", reason="Explicit opt-in real local model test")
def test_real_cpu_cross_encoder_smoke(monkeypatch):
    """No downloads here. Save synthetic latency/RSS observations in reports/."""
    import psutil
    import time
    def no_network(*args, **kwargs):
        pytest.fail("Real local inference attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    process = psutil.Process()
    start_rss = process.memory_info().rss
    begin = time.perf_counter()
    model_identity = reranking.reranker_identity("cross_encoder")
    scorer = reranking.get_scorer(model_identity)
    load_seconds = time.perf_counter() - begin
    passages = candidates()
    passages[0]["text"] = "Risk management process includes hazard analysis and residual risk evaluation. " * 100
    begin = time.perf_counter()
    result = reranking.rerank_candidates("risk management evidence", passages, backend="cross_encoder", scorer=scorer, identity=model_identity)
    elapsed = time.perf_counter() - begin
    assert len(result["diagnostics"]["scores"]) == 3
    assert all(math.isfinite(s["score"]) for s in result["diagnostics"]["scores"])
    assert result["diagnostics"]["scores"][0]["passage_truncated"]
    assert all(p.device.type == "cpu" for p in scorer.encoder.model.parameters())
    assert str(next(scorer.encoder.model.parameters()).dtype) == "torch.float32"
    thirty = [dict(id=f"D-{n}", text=passages[n % 3]["text"], meta=dict(passages[n % 3]["meta"], block=n+1)) for n in range(30)]
    begin = time.perf_counter()
    bounded_result = reranking.rerank_candidates("risk management evidence", thirty, backend="cross_encoder", scorer=scorer, identity=model_identity)
    thirty_elapsed = time.perf_counter() - begin
    assert len(bounded_result["diagnostics"]["scores"]) == 30
    out = Path("reports/stage4-real-smoke/metrics.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"identity": model_identity, "load_seconds": load_seconds,
        "three_pair_seconds": elapsed, "thirty_pair_seconds": thirty_elapsed, "rss_before_bytes": start_rss,
        "process_peak_rss_bytes": getattr(process.memory_info(), "peak_wset", None),
        "rss_after_bytes": process.memory_info().rss, "diagnostics": result["diagnostics"],
        "limitation": "Synthetic one-run CPU smoke observations; peak RSS includes imports and model load. Not a production throughput benchmark."}, indent=2))
