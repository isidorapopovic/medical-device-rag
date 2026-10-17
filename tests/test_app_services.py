"""Offline service/CLI/Streamlit acceptance with real temporary Chroma storage."""
import json

import chromadb
from chromadb.config import Settings
import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

from mdr_rag import app_services as services, core, pipeline, search
from mdr_rag.document_ui import ingest_uploaded_document


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    import streamlit_app
    documents, state = tmp_path / "documents", tmp_path / "state"
    monkeypatch.setattr(core, "DOCS", documents)
    monkeypatch.setattr(core, "STATE", state)
    monkeypatch.setattr(pipeline, "DOCS", documents)
    monkeypatch.setattr(pipeline, "STATE", state)
    monkeypatch.setattr(streamlit_app, "DOCS", documents)
    monkeypatch.setenv("EMBEDDING_MODEL", "synthetic-offline")
    database = chromadb.PersistentClient(path=str(tmp_path / "chroma"),
                                        settings=Settings(anonymized_telemetry=False))
    monkeypatch.setattr(search, "open_db", lambda: database)
    monkeypatch.setattr(search, "embeddings", lambda texts: [[1., float(len(t)), 0.] for t in texts])
    for kind in ("legal", "device"):
        (documents / kind).mkdir(parents=True)
    return documents, state, database


def add_text(workspace):
    path = workspace[0] / "device" / "toy.txt"
    path.write_text("SYNTHETIC DEVICE SOURCE ONLY", encoding="utf-8")
    return path


def app():
    return AppTest.from_string("import streamlit_app as app\napp.main()", default_timeout=30).run()


def index_button(ui):
    return next(button for button in ui.button if button.label == "Index Documents")


def test_missing_manifest_is_not_indexed(workspace):
    status = services.get_index_status()
    assert status.state == "Not indexed" and not status.can_index
    assert index_button(app()).disabled


def test_upload_alone_does_not_mark_ready(workspace):
    ingest_uploaded_document("device", "toy.txt", b"SYNTHETIC UPLOAD", documents_root=workspace[0])
    assert services.get_index_status().state == "Not indexed"
    ui = app()
    ui.session_state["documents_saved"] = True
    ui.run()
    assert any("Index out of date" in item.value for item in ui.subheader)
    assert not index_button(ui).disabled
    assert not (workspace[1] / "manifest.json").exists()


def test_success_metrics_and_restart(workspace):
    add_text(workspace)
    result = services.index_documents()
    assert result.success and result.status.state == "Ready"
    assert result.status.file_count == result.status.chunk_count == 1
    assert result.status.indexed_at and result.status.embedding_model == "synthetic-offline"
    assert any("Ready" in item.value for item in app().subheader)


@pytest.mark.parametrize("change", ["added", "removed", "modified", "model"])
def test_stale_manifest(workspace, monkeypatch, change):
    path = add_text(workspace)
    assert services.index_documents().success
    if change == "added":
        (workspace[0] / "legal" / "new.md").write_text("SYNTHETIC LEGAL", encoding="utf-8")
    elif change == "removed":
        path.unlink()
    elif change == "modified":
        path.write_text("SYNTHETIC CHANGED", encoding="utf-8")
    else:
        monkeypatch.setenv("EMBEDDING_MODEL", "other-model")
    status = services.get_index_status()
    assert status.state == "Index out of date"
    assert any(word in status.reason.lower() for word in ("added", "removed", "changed"))


@pytest.mark.parametrize("damage", ["missing", "incomplete", "wrong_audit", "invalid_manifest"])
def test_collection_and_audit_must_match(workspace, damage):
    add_text(workspace)
    assert services.index_documents().success
    active = search.collection()
    if damage == "missing":
        workspace[2].delete_collection(search.COLLECTION)
    elif damage == "incomplete":
        active.delete(ids=active.get()["ids"])
    elif damage == "wrong_audit":
        active.modify(metadata={"embedding_model": "synthetic-offline", "index_fingerprint": "wrong"})
    else:
        (workspace[1] / "manifest.json").write_text('{"files": null}', encoding="utf-8")
    assert services.get_index_status().state == "Index out of date"


def test_failure_is_visible_retryable_and_logs_details(workspace, monkeypatch, caplog):
    add_text(workspace)
    def fail(texts):
        raise RuntimeError("SYNTHETIC PRIVATE PROVIDER DETAIL")
    monkeypatch.setattr(search, "embeddings", fail)
    ui = app()
    index_button(ui).click().run()
    assert not ui.exception
    assert any("retry" in item.value for item in ui.error)
    assert all("PRIVATE PROVIDER DETAIL" not in item.value for item in ui.error)
    assert "SYNTHETIC PRIVATE PROVIDER DETAIL" in caplog.text
    assert not index_button(ui).disabled


def test_blank_pdf_warns_about_ocr_and_disables_index(workspace):
    with pymupdf.open() as pdf:
        pdf.new_page()
        (workspace[0] / "legal" / "scan.pdf").write_bytes(pdf.tobytes())
    status = services.get_index_status()
    assert not status.can_index and any("OCR" in warning for warning in status.warnings)
    assert index_button(app()).disabled


def test_cli_still_indexes_and_writes_compatible_manifest(workspace, monkeypatch, capsys):
    import main
    add_text(workspace)
    monkeypatch.setattr("sys.argv", ["main.py", "index"])
    assert main.main() == 0
    audit = json.loads((workspace[1] / "manifest.json").read_text(encoding="utf-8"))
    assert pipeline.check_manifest() == audit
    assert "Indexed 1 chunks from 1 files" in capsys.readouterr().out
    assert services.get_index_status().state == "Ready"


def test_manifest_write_failure_does_not_advertise_new_collection(workspace, monkeypatch):
    path = add_text(workspace)
    assert services.index_documents().success
    old_audit = (workspace[1] / "manifest.json").read_bytes()
    path.write_text("SYNTHETIC CHANGED DEVICE", encoding="utf-8")
    def fail(*args):
        raise OSError("SYNTHETIC disk failure")
    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "save_json", fail)
        assert not services.index_documents().success
    assert (workspace[1] / "manifest.json").read_bytes() == old_audit
    assert services.get_index_status().state == "Index out of date"
    assert services.index_documents().success


def test_pdf_acceptance_upload_index_restart_add_reindex(workspace, monkeypatch):
    # Real PDF extraction and Chroma, with only model inference replaced.
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "SYNTHETIC LEGAL TEXT FOR OFFLINE ACCEPTANCE")
        content = pdf.tobytes()
    ingest_uploaded_document("legal", "toy.pdf", content, documents_root=workspace[0])
    ui = app()
    ui.session_state["documents_saved"] = True
    ui.run()
    assert any("Index out of date" in item.value for item in ui.subheader)
    index_button(ui).click().run()
    assert not ui.exception
    assert ui.success and any("Ready" in item.value for item in ui.subheader)
    assert services.get_index_status().chunk_count > 0
    assert any("Ready" in item.value for item in app().subheader)
    add_text(workspace)
    ui = app()
    assert any("Index out of date" in item.value for item in ui.subheader)
    index_button(ui).click().run()
    assert services.get_index_status().file_count == 2
    assert any("Ready" in item.value for item in ui.subheader)
    # Ordinary reruns must not trigger indexing.
    monkeypatch.setattr(services.pipeline, "run_index", lambda: pytest.fail("Unexpected rerun indexing"))
    ui.run()
    assert not ui.exception
