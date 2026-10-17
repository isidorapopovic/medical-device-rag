"""Source-scoped single-turn Q&A: real local storage, mocked model inference."""
import re

import pymupdf
import pytest
from docx import Document

from mdr_rag import pipeline, search, app_services as services
from mdr_rag.qa_types import AnswerResult
from mdr_rag.schemas import StructuredAnswer, StructuredClaim, QuotedReference, FindingReview
from test_app_services import workspace, app
from test_report_state import reviewer


@pytest.fixture
def documents(workspace, monkeypatch):
    for name, text in (("alpha.pdf", "SYNTHETIC ALPHA: maintain risk management records."),
                       ("beta.pdf", "SYNTHETIC BETA: prepare separate clinical evaluation.")):
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), text)
            (workspace[0] / "legal" / name).write_bytes(pdf.tobytes())
    doc = Document()
    doc.add_paragraph("SYNTHETIC DEVICE: maintain calibration records.")
    doc.save(workspace[0] / "device" / "alpha.docx")
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("RERANK_BACKEND", "none")
    assert services.index_documents().success
    return workspace


def model(monkeypatch, *, failure=None):
    calls = []
    def generate(rules, prompt, schema):
        calls.append((schema, prompt))
        if schema is FindingReview:
            if failure == "review_error":
                raise ConnectionError("SYNTHETIC PRIVATE DETAILS")
            result = reviewer(prompt)
            if failure == "rejected":
                result.claims[0].verdict = "insufficient"
            return result
        if failure == "generation_error":
            raise ConnectionError("SYNTHETIC PRIVATE DETAILS")
        if failure == "malformed":
            return {"wrong": "shape"}
        chunk, source, text = re.search(r"SOURCE_ID: (.+)\nLOCATION: (.+)\nTEXT: ([^\n]+)", prompt).groups()
        legal = source.startswith("legal/")
        quote = "invented quote not in the source" if failure == "quote" else text
        return StructuredAnswer(claims=[StructuredClaim(
            claim_id="A1", text="The selected source discusses records.",
            role="legal_duty" if legal else "device_fact", category="assessment", obligation_ids=[],
            evidence=[] if failure == "no_citation" else [QuotedReference(
                source_id=chunk, exact_quote=quote, purpose="legal_basis" if legal else "device_support")])],
            source_ids=[chunk, "L-invented"] if failure == "unknown_id" else [chunk], limitations=[])
    monkeypatch.setattr(pipeline, "llm_parse", generate)
    return calls


@pytest.mark.parametrize("selection", [{"legal/alpha.pdf"}, {"device/alpha.docx"},
                                      {"legal/alpha.pdf", "device/alpha.docx"}])
def test_typed_answer_uses_only_selected_sources(documents, monkeypatch, selection):
    calls = model(monkeypatch)
    result = services.ask_question("What records are discussed?", selection)
    assert isinstance(result, AnswerResult) and result.status == "supported"
    assert result.sources and {source.source for source in result.sources} <= selection
    rows = search.collection().get(include=["documents", "metadatas"])
    indexed = dict(zip(rows["ids"], zip(rows["documents"], rows["metadatas"])))
    for source in result.sources:
        text, meta = indexed[source.id]
        assert source.excerpt == text and source.source == meta["source"]
        assert (source.page, source.block) == (meta["page"], meta["block"])
    for _, prompt in calls:
        for source in {"legal/alpha.pdf", "legal/beta.pdf", "device/alpha.docx"} - selection:
            assert source not in prompt


@pytest.mark.parametrize("failure", ["unknown_id", "quote", "no_citation", "rejected", "review_error"])
def test_audit_failure_never_publishes_answer_or_sources(documents, monkeypatch, failure):
    model(monkeypatch, failure=failure)
    result = services.ask_question("What records?", {"legal/alpha.pdf"})
    assert result.status == "verification_failed" and not result.sources
    assert "The selected source discusses records." not in result.answer
    assert result.error if failure == "review_error" else result.error is None


@pytest.mark.parametrize("failure", ["generation_error", "malformed"])
def test_technical_errors_are_actionable_and_sanitized(documents, monkeypatch, failure):
    model(monkeypatch, failure=failure)
    result = services.ask_question("What records?", {"legal/alpha.pdf"})
    assert result.status == "error" and result.error and not result.sources and not result.answer
    assert "PRIVATE" not in result.error
    assert "retry" in result.error.lower() or "Retry" in result.error


def test_empty_selection_and_unknown_document_never_generate(documents, monkeypatch):
    calls = model(monkeypatch)
    for selection in (set(), {"legal/missing.pdf"}):
        assert services.ask_question("Question", selection).status == "invalid_selection"
    assert not calls


def test_empty_retrieval_is_explicit_insufficient_evidence(documents, monkeypatch):
    calls = model(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    result = services.ask_question("unmatchedgibberish", {"legal/alpha.pdf"})
    assert result.status == "insufficient_evidence" and not result.sources
    assert "Insufficient evidence" in result.answer and not calls


def test_cli_uses_shared_operation_and_keeps_citation_output(documents, monkeypatch, capsys):
    model(monkeypatch)
    result = pipeline.run_ask("What records?")
    output = capsys.readouterr().out
    assert result.status == "supported"
    assert "ANSWER:" in output and "VERIFIED RETRIEVAL CITATIONS:" in output and "LIMITATIONS:" in output
    for source in result.sources:
        assert f"[{source.id}] {source.source}" in output


def ask_button(ui):
    return next(button for button in ui.button if button.label == "Ask")


def test_ui_acceptance_filtered_pdf_then_docx_and_no_duplicate_calls(documents, monkeypatch):
    calls = model(monkeypatch)
    ui = app()
    assert set(ui.multiselect[0].value) == {"legal/alpha.pdf", "legal/beta.pdf", "device/alpha.docx"}
    ui.multiselect[0].set_value(["legal/alpha.pdf"]).run()
    ui.text_area(key="single_question").set_value("What records?")
    ask_button(ui).click().run()
    assert not ui.exception
    assert any("Supported" in item.value for item in ui.success)
    assert any("legal/alpha.pdf" in item.label and "PDF page" in item.label for item in ui.expander)
    assert any("SYNTHETIC ALPHA" in item.value for item in ui.text)
    count = len(calls)
    ui.run()
    assert len(calls) == count
    ui.multiselect[0].set_value(["device/alpha.docx"]).run()
    assert not ui.expander  # An old answer must not appear under a new selection.
    ask_button(ui).click().run()
    assert not ui.exception
    assert any("device/alpha.docx" in item.label and "text block" in item.label for item in ui.expander)
    assert any("SYNTHETIC DEVICE" in item.value for item in ui.text)
    assert all("legal/alpha.pdf" not in item.label for item in ui.expander)


def test_ui_empty_selection_and_collection_shortcuts(documents):
    ui = app()
    radio = next(r for r in ui.radio if r.label == "Source collections")
    radio.set_value("Device only").run()
    assert ui.multiselect[0].value == ["device/alpha.docx"]
    ui.multiselect[0].set_value([]).run()
    assert ask_button(ui).disabled


@pytest.mark.parametrize("problem", ["missing", "stale"])
def test_invalid_index_blocks_service_and_ui(documents, monkeypatch, problem):
    calls = model(monkeypatch)
    if problem == "missing":
        (documents[1] / "manifest.json").unlink()
    else:
        (documents[0] / "device" / "new.txt").write_text("SYNTHETIC new file", encoding="utf-8")
    result = services.ask_question("What records?")
    assert result.status == "index_invalid" and not calls
    ui = app()
    assert ask_button(ui).disabled and not ui.multiselect[0].options


def test_ui_model_failure_remains_usable_and_explicit(documents, monkeypatch):
    model(monkeypatch, failure="generation_error")
    ui = app()
    ui.text_area(key="single_question").set_value("What records?")
    ask_button(ui).click().run()
    assert not ui.exception and ui.error
    assert not ask_button(ui).disabled and not ui.expander
    assert "Ollama" in ui.error[0].value and "PRIVATE" not in ui.error[0].value


def test_ui_insufficient_evidence_is_distinct_from_technical_failure(documents, monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    ui = app()
    ui.text_area(key="single_question").set_value("unmatchedgibberish")
    ask_button(ui).click().run()
    assert not ui.exception and not ui.error
    assert any("Insufficient evidence" in item.value for item in ui.warning)


@pytest.fixture
def filter_corpus(workspace, monkeypatch):
    database = workspace[2]
    active = database.create_collection(search.COLLECTION, embedding_function=None)
    records = [(f"L-{n:02}", f"legal/excluded{n}.txt", "chosenneedle excluded") for n in range(18)]
    records += [("L-selected", "legal/shared.pdf", "chosenneedle selected legal"),
                ("D-selected", "device/shared.pdf", "chosenneedle selected device")]
    active.add(ids=[r[0] for r in records], documents=[r[2] for r in records],
               metadatas=[{"kind": r[1].split("/")[0], "source": r[1], "page": 1, "block": 1} for r in records],
               embeddings=[[1., 0., 0.] for _ in records])
    monkeypatch.setattr(search, "embeddings", lambda queries: [[1., 0., 0.] for _ in queries])
    search._BM25_CACHE.clear()
    return records


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
@pytest.mark.parametrize("rerank", [False, True])
@pytest.mark.parametrize("selection", [{"legal/shared.pdf"}, {"legal/shared.pdf", "device/shared.pdf"},
                                      {"device/shared.pdf"}, set(), {"legal/missing.pdf"}])
def test_filters_before_top_k_and_reranking(filter_corpus, monkeypatch, mode, rerank, selection):
    seen = []
    def rank(query, passages):
        assert {p["meta"]["source"] for p in passages} <= selection
        seen.extend(passages)
        return passages
    monkeypatch.setattr(search, "rerank_passages", rank)
    result = []
    for kind in ("legal", "device"):
        result.extend(search.hybrid_search("chosenneedle", kind, k=1, mode=mode, rerank=rerank, sources=selection))
    expected = selection & {"legal/shared.pdf", "device/shared.pdf"}
    assert {p["meta"]["source"] for p in result} == expected
    assert bool(seen) == bool(rerank and expected)


def test_backend_filter_and_local_defense_and_scoped_cache(workspace, monkeypatch):
    calls = []
    class Collection:
        id = "SYNTHETIC"
        def get(self, **kwargs):
            calls.append(kwargs["where"])
            # A faulty backend cannot pass excluded passages into BM25.
            return {"ids": ["L-1", "L-2"], "documents": ["chosenneedle alpha", "chosenneedle beta"],
                    "metadatas": [{"kind": "legal", "source": "legal/alpha.pdf"},
                                  {"kind": "legal", "source": "legal/beta.pdf"}]}
        def query(self, **kwargs):
            calls.append(kwargs["where"])
            return {"ids": [["L-2", "L-1"]]}
    monkeypatch.setattr(search, "collection", Collection)
    search._BM25_CACHE.clear()
    for source in ("legal/alpha.pdf", "legal/beta.pdf"):
        result = search.retrieve_candidates(["chosenneedle"], "legal", mode="hybrid", rerank=False,
                                            sources={source}, manifest_fingerprint="same-index")
        assert {p["meta"]["source"] for p in result["passages"]} == {source}
        assert calls[-2:] == [{"$and": [{"kind": "legal"}, {"source": {"$in": [source]}}]}] * 2
