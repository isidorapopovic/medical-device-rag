"""Stage 00 compatibility checks; all device text is invented test content."""
import json
import sys

import pytest

import main
from mdr_rag import core, pipeline, search
from mdr_rag.document_ui import save_uploaded_document


@pytest.mark.parametrize("argv", [["inspect"], ["locate", "toy phrase"], ["index"],
                                  ["ask", "toy question"], ["extract", "--pages", "1-2"],
                                  ["review", "--limit", "1", "--k", "3"]])
def test_legacy_cli_dispatch(monkeypatch, argv):
    calls = []
    for name in ("inspect_files", "run_index", "run_ask", "extract_requirements", "run_review"):
        monkeypatch.setattr(main, name, lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    assert main.main() == 0
    assert len(calls) == 1


@pytest.mark.parametrize("argv", [["ask"], ["extract"], ["--retrieval", "invalid", "inspect"],
                                  ["--rerank", "--rerank-backend", "none", "inspect"]])
def test_invalid_cli_fails_before_dispatch(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 2


def test_empty_corpora_and_duplicate_unicode_names(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "DOCS", tmp_path)
    assert core.all_records() == ([], [], [])
    for kind in ("legal", "device"):
        save_uploaded_document(kind, "toy uređaj notes.txt", b"Invented toy fixture only.", tmp_path)
    records, warnings, manifest = core.all_records()
    assert not warnings
    assert {r["meta"]["source"] for r in records} == {
        "legal/toy uređaj notes.txt", "device/toy uređaj notes.txt"}
    assert len({r["id"] for r in records}) == len(manifest) == 2
    with pytest.raises(FileExistsError):
        save_uploaded_document("device", "toy uređaj notes.txt", b"replacement", tmp_path)


def test_citation_output_contract():
    assert core.location({"source": "legal/toy.pdf", "page": 2}) == "legal/toy.pdf, PDF page 2"
    assert core.location({"source": "device/toy.txt", "page": 0, "block": 1}) == (
        "device/toy.txt, text block 1 (no stable page number)")


def test_empty_index_does_not_open_database(monkeypatch):
    monkeypatch.setattr(search, "all_records", lambda: ([], [], []))
    monkeypatch.setattr(search, "open_db", lambda: pytest.fail("Empty input must not mutate index"))
    with pytest.raises(RuntimeError, match="Add PDFs"):
        search.rebuild_index()


def test_invalid_retrieval_config_does_not_open_database(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "invalid")
    monkeypatch.setattr(search, "collection", lambda: pytest.fail("Invalid config must fail first"))
    with pytest.raises(ValueError, match="RETRIEVAL_MODE"):
        search.retrieve_candidates(["toy"], "device")


def test_missing_manifest_is_safe_cli_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pipeline, "STATE", tmp_path)
    monkeypatch.setattr(sys, "argv", ["main.py", "ask", "toy question"])
    monkeypatch.setattr(search, "embeddings", lambda *a: pytest.fail("Must not infer"))
    assert main.main() == 1
    assert "ERROR:" in capsys.readouterr().err


def test_malformed_json_is_explicit(tmp_path):
    path = tmp_path / "toy.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        pipeline.load_json(path)


def test_offline_ollama_error_is_propagated_without_retry(monkeypatch):
    import ollama
    calls = []
    def offline(**kwargs):
        calls.append(kwargs)
        raise ConnectionError("synthetic offline Ollama")
    monkeypatch.setattr(ollama, "embed", offline)
    with pytest.raises(ConnectionError, match="synthetic offline"):
        search.embeddings(["Invented toy fixture only."])
    assert len(calls) == 1
