import pytest

from mdr_rag.document_ui import save_uploaded_document


def test_upload_saves_supported_document_inside_selected_corpus(tmp_path):
    saved = save_uploaded_document(
        "legal", "regulation.PDF", b"pdf contents", documents_root=tmp_path
    )

    assert saved == tmp_path / "legal" / "regulation.PDF"
    assert saved.read_bytes() == b"pdf contents"


def test_upload_rejects_unsupported_type_and_existing_filename(tmp_path):
    with pytest.raises(ValueError, match="Supported file types"):
        save_uploaded_document("device", "payload.exe", b"data", documents_root=tmp_path)

    save_uploaded_document("device", "risk.txt", b"original", documents_root=tmp_path)
    with pytest.raises(FileExistsError, match="already exists"):
        save_uploaded_document("device", "risk.txt", b"replacement", documents_root=tmp_path)
    assert (tmp_path / "device" / "risk.txt").read_bytes() == b"original"


def test_upload_cannot_escape_documents_root(tmp_path):
    saved = save_uploaded_document(
        "device", "..\\outside.txt", b"safe", documents_root=tmp_path
    )

    assert saved.parent == tmp_path / "device"
    assert saved.name == "outside.txt"
