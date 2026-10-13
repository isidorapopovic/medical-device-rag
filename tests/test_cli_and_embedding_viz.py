import os
from unittest.mock import Mock

import numpy as np

import main
from mdr_rag import embedding_viz


def test_retrieval_override_before_command(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setattr("sys.argv", ["main.py", "--retrieval", "bm25", "ask", "Synthetic question"])
    received = []
    monkeypatch.setattr(main, "run_ask", lambda question: received.append((question, os.environ["RETRIEVAL_MODE"])))
    assert main.main() == 0
    assert received == [("Synthetic question", "bm25")]


def test_rerank_flag_enables_local_reranking(monkeypatch):
    monkeypatch.delenv("RERANK_BACKEND", raising=False)
    monkeypatch.delenv("RERANK_ENABLED", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", "--rerank", "ask", "Synthetic question"])
    received = []
    monkeypatch.setattr(
        main, "run_ask",
        lambda question: received.append((question, os.environ["RERANK_ENABLED"])),
    )

    assert main.main() == 0
    assert received == [("Synthetic question", "true")]


def test_embedding_plot_with_query(monkeypatch, tmp_path):
    monkeypatch.setattr(embedding_viz, "check_manifest", lambda: None)
    fake = Mock()
    fake.get.return_value = {
        "ids": ["L-1", "D-1", "D-2"],
        "embeddings": np.eye(3),
        "documents": ["Legal text", "Device text", "More evidence"],
        "metadatas": [
            {"kind": "legal", "source": "legal.txt", "page": 1},
            {"kind": "device", "source": "device.txt", "page": 1},
            {"kind": "device", "source": "device.txt", "page": 2},
        ],
    }
    monkeypatch.setattr(embedding_viz, "collection", lambda: fake)
    monkeypatch.setattr(embedding_viz, "embeddings", lambda texts: [[1.0, 0.0, 0.0]])
    destination = tmp_path / "map.html"
    health = embedding_viz.visualize_embeddings(600, "Synthetic query", destination)
    assert destination.exists()
    assert destination.with_suffix(".json").exists()
    assert health["query_nearest_by_cosine_in_sample"][0]["id"] == "L-1"
