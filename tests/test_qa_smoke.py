"""Opt-in local-model smoke; retains the application's real model and audit paths."""
import os

import pytest
import pymupdf
import chromadb
from chromadb.config import Settings

from mdr_rag import app_services as services, core, pipeline, search, runtime
from mdr_rag.settings import load_settings


@pytest.mark.real_model
@pytest.mark.skipif(os.getenv("RUN_QA_SMOKE") != "1", reason="Set RUN_QA_SMOKE=1 with local Ollama running")
def test_real_document_questions(tmp_path, monkeypatch):
    """Use one real uploaded PDF page without replacing the user's index or files."""
    inputs = sorted((core.DOCS / "legal").glob("*.pdf"))
    if not inputs:
        pytest.skip("A text-readable legal PDF in documents/legal is required")
    documents = tmp_path / "documents"
    (documents / "legal").mkdir(parents=True)
    with pymupdf.open(inputs[0]) as original:
        readable = next((i for i, page in enumerate(original) if len(page.get_text().strip()) > 200), None)
        if readable is None:
            pytest.skip("The first uploaded legal PDF has no text-readable page")
        with pymupdf.open() as excerpt:
            excerpt.insert_pdf(original, from_page=readable, to_page=readable)
            excerpt.save(documents / "legal" / "real-page.pdf")
    monkeypatch.setattr(core, "DOCS", documents)
    monkeypatch.setattr(pipeline, "DOCS", documents)
    monkeypatch.setattr(pipeline, "STATE", tmp_path / "state")
    monkeypatch.setenv("RUNTIME_DATABASE", str(tmp_path / "runtime.sqlite3"))
    monkeypatch.setattr(runtime, "load_settings", lambda: load_settings(root=tmp_path, env_file=core.ROOT / ".env"))
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("RERANK_BACKEND", "none")
    # A smoke-only override selects an already installed model without altering .env.
    if smoke_model := os.getenv("QA_SMOKE_MODEL"):
        monkeypatch.setenv("OLLAMA_LLM_MODEL", smoke_model)
    database = chromadb.PersistentClient(path=str(tmp_path / "chroma"),
                                        settings=Settings(anonymized_telemetry=False))
    monkeypatch.setattr(search, "open_db", lambda: database)
    indexed = services.index_documents()
    assert indexed.success, indexed.error
    questions = (
        "Which regulation number and date are printed in the selected page? Cite only the printed text.",
        "What is the serial number of the Mars Rover medical scanner bought by Alice Example in 2099?",
    )
    results = []
    for question in questions:
        result = services.ask_question(question, {"legal/real-page.pdf"}, k=1)
        results.append(result)
        print(f"LIVE_QA status={result.status} sources={len(result.sources)} error={result.error}")
        assert result.status in {"supported", "insufficient_evidence", "verification_failed"}, result.error
        assert all(source.source == "legal/real-page.pdf" for source in result.sources)
    assert results[1].status != "supported", "An absent serial number must not be presented as supported"
