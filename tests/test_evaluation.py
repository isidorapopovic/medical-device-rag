"""API-free unit tests for diagnostic mathematics and graph provenance."""
import json
import math
import os
import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest

from mdr_rag.embedding_viz import embedding_statistics, unit_vectors
from mdr_rag import evaluation, search, pipeline
from mdr_rag.evaluation import fusion, load_gold, rank_scores
from mdr_rag.graph_viz import build_evidence_graph
from mdr_rag.search import rerank_passages


def test_cosine_unit_vector():
    normalized = unit_vectors([[3.0, 4.0], [0.0, 10.0]])
    assert np.allclose(np.linalg.norm(normalized, axis=1), [1, 1])
    with pytest.raises(ValueError):
        unit_vectors([[0.0, 0.0]])


def test_near_duplicates():
    rows = embedding_statistics([[1, 0], [1, 0], [0, 1]], ["a", "b", "c"],
                                [{"kind": "legal"}] * 3)
    assert rows["near_duplicate_pairs_found_in_scan"] == 1


def test_retrieval_metrics_distinct_page_labels():
    labels = [{"source": "legal/m.pdf", "page": 1}, {"source": "legal/m.pdf", "page": 2}]
    metas = {"a": {"source": "legal/m.pdf", "page": 1},
             "b": {"source": "legal/m.pdf", "page": 1},
             "c": {"source": "legal/m.pdf", "page": 2}}
    scores = rank_scores(["a", "b", "c"], metas, labels, 3)
    assert math.isclose(scores["recall"], 1)
    assert math.isclose(scores["precision"], 2/3)
    assert math.isclose(scores["mrr"], 1)
    assert scores["ndcg"] < 1


def test_retrieval_zero_hits():
    scores = rank_scores(["a"], {"a": {"source": "device/q.pdf", "page": 1}},
                         [{"source": "legal/m.pdf", "page": 1}], 1)
    assert scores["recall"] == 0
    assert scores["mrr"] == 0


def test_fusion_excludes_nonmatching_bm25():
    result = fusion(["A"], ["B"], {"A": 0, "B": 0}, 3)
    assert result == ["A"]


def test_local_reranker_orders_candidates_and_requires_complete_ids(monkeypatch):
    import json

    candidates = [
        {"id": "A", "text": "General information", "meta": {}},
        {"id": "B", "text": "Directly relevant evidence", "meta": {}},
    ]
    fake_ollama = SimpleNamespace(
        chat=lambda **kwargs: {
            "message": {
                "content": json.dumps({"scores": [
                    {"source_id": "B", "score": 90},
                    {"source_id": "A", "score": 20},
                ]})
            }
        }
    )
    monkeypatch.setitem(sys.modules, "ollama", fake_ollama)
    assert [p["id"] for p in rerank_passages("question", candidates)] == ["B", "A"]

    fake_ollama.chat = lambda **kwargs: {
        "message": {"content": json.dumps({"scores": [{"source_id": "B", "score": 90}]})}
    }
    with pytest.raises(RuntimeError, match="missing, duplicate, or unknown"):
        rerank_passages("question", candidates)


def test_evaluate_reports_hybrid_reranking_against_gold(monkeypatch, tmp_path):
    ids = ["A", "B", "C"]
    docs = ["general information", "risk management process", "clinical evidence"]
    metadata = [
        {"kind": "legal", "source": "legal/a.pdf", "page": 1},
        {"kind": "legal", "source": "legal/a.pdf", "page": 2},
        {"kind": "legal", "source": "legal/a.pdf", "page": 3},
    ]

    class FakeCollection:
        def get(self, **kwargs):
            return {"ids": ids, "documents": docs, "metadatas": metadata}

        def query(self, **kwargs):
            return {"ids": [["A", "B", "C"]]}

    monkeypatch.setattr(
        evaluation, "check_manifest",
        lambda: {"files": [{"source": "legal/a.pdf", "sha256": "hash"}],
                 "embedding_model": "test-embedding"},
    )
    monkeypatch.setattr(search, "collection", FakeCollection)
    monkeypatch.setattr(search, "embeddings", lambda texts: [[1.0, 0.0]])
    monkeypatch.setattr(
        search, "rerank_passages",
        lambda query, passages: sorted(passages, key=lambda p: p["id"] != "C"),
    )
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps([{
        "id": "Q1",
        "query": "risk management process",
        "kind": "legal",
        "relevant": [{"source": "legal/a.pdf", "page": 3}],
    }]))

    monkeypatch.setattr(pipeline, "check_manifest", evaluation.check_manifest)
    report = evaluation.evaluate(
        gold_path=gold_path,
        ks=(1,),
        destination=tmp_path / "report.json",
        include_reranked=True,
    )

    hybrid = next(row for row in report["average_metrics"] if row["method"] == "hybrid")
    reranked = next(
        row for row in report["average_metrics"] if row["method"] == "hybrid_llm"
    )
    assert hybrid["recall"] == 0
    assert reranked["recall"] == 1
    assert next(row for row in report["per_query"] if row["method"] == "hybrid_llm")["identity"]["model"] == os.getenv("OLLAMA_LLM_MODEL", "qwen3:4b")


def test_gold_rejects_empty_and_bad_page(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text("[]")
    with pytest.raises(ValueError):
        load_gold(path)
    path.write_text(json.dumps([{"id": "Q", "kind": "legal", "query": "q",
                                 "relevant": [{"source": "legal/a.pdf", "page": 0}]}]))
    with pytest.raises(ValueError):
        load_gold(path)


def test_graph_counts_only_verified_retrieved_citations():
    report = {"findings": [
        {"requirement": {"id": "R1", "requirement": "Example"},
         "finding": {"status": "supported", "evidence_ids": ["D1", "DFAKE"]},
         "retrieved_evidence": [{"id": "D1", "source": "device/example.pdf", "page": 4}]},
        {"requirement": {"id": "R2"},
         "finding": {"status": "not_found", "evidence_ids": []},
         "retrieved_evidence": []},
    ]}
    graph, stats = build_evidence_graph(report)
    assert stats["requirements_with_cited_evidence"] == 1
    assert stats["requirements_without_cited_evidence"] == 1
    assert stats["verified_requirement_to_evidence_edges"] == 1
    assert len(stats["missing_citation_references"]) == 1
    assert graph.number_of_nodes() == 4
