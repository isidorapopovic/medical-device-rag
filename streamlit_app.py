"""Local Streamlit interface for managing and previewing RAG source documents."""
from pathlib import Path

import streamlit as st

from mdr_rag.core import DOCS, source_records
from mdr_rag.document_ui import SUPPORTED_EXTENSIONS, ingest_uploaded_document
from mdr_rag.ingestion import confined, extraction_warnings

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PREVIEW_CHAR_LIMIT = 12_000
SUPPORTED_TYPES = sorted(extension.lstrip(".") for extension in SUPPORTED_EXTENSIONS)


def list_documents(kind: str) -> list[Path]:
    if kind not in {"legal", "device"}:
        raise ValueError("Document type must be legal or device")
    folder = confined(DOCS, DOCS / kind)
    folder.mkdir(parents=True, exist_ok=True)
    allowed = []
    for path in folder.iterdir():
        try:
            confined(DOCS, path)
        except ValueError:
            continue
        if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS:
            allowed.append(path)
    return sorted(allowed, key=lambda path: path.name.casefold())


def main() -> None:
    st.set_page_config(page_title="Medical Device RAG", page_icon="📄", layout="wide")
    st.title("Medical Device RAG")
    st.caption("Upload and preview local legal and device source documents.")
    st.info(
        "Files are stored in this project's documents folder. Uploading does not index "
        "them or send them to a model. This app has no authentication; keep it bound to "
        "localhost and do not expose it to a network."
    )

    with st.sidebar:
        st.header("Upload documents")
        kind = st.radio(
            "Document category",
            options=["legal", "device"],
            format_func=lambda value: "Legal / regulatory" if value == "legal" else "Device",
        )
        uploads = st.file_uploader(
            "Choose PDF, DOCX, TXT or Markdown files",
            type=SUPPORTED_TYPES,
            accept_multiple_files=True,
        )
        if st.button("Save selected files", type="primary", disabled=not uploads):
            for upload in uploads or []:
                content = upload.getvalue()
                if len(content) > MAX_UPLOAD_BYTES:
                    st.error(f"{upload.name}: file exceeds the 50 MiB upload limit")
                    continue
                try:
                    saved_path, ingested, manifest_hash = ingest_uploaded_document(kind, upload.name, content)
                except (OSError, ValueError) as exc:
                    st.error(f"{upload.name}: {exc}")
                else:
                    st.success(f"Saved {saved_path.relative_to(DOCS)}")
                    st.caption(f"Archived revision {ingested.document.version}; status: {ingested.extraction.status}; manifest: {manifest_hash}")
                    for warning in extraction_warnings(ingested):
                        st.warning(warning)

    legal_documents = list_documents("legal")
    device_documents = list_documents("device")
    summary_left, summary_right = st.columns(2)
    summary_left.metric("Legal / regulatory files", len(legal_documents))
    summary_right.metric("Device files", len(device_documents))

    category = st.selectbox(
        "Browse category",
        options=["legal", "device"],
        format_func=lambda value: "Legal / regulatory" if value == "legal" else "Device",
    )
    documents = list_documents(category)
    if not documents:
        st.warning(f"No supported documents uploaded to the {category} collection yet.")
        return

    selected = st.selectbox(
        "Select a document",
        options=documents,
        format_func=lambda path: path.name,
    )
    st.caption(f"{selected.stat().st_size:,} bytes · {selected.suffix.upper()}")
    st.download_button(
        "Download original",
        data=selected.read_bytes(),
        file_name=selected.name,
        mime="application/octet-stream",
    )

    try:
        records, warnings = source_records(selected, category)
    except Exception as exc:
        st.error(f"Could not extract preview text: {exc}")
        return

    for warning in warnings:
        st.warning(warning)
    if not records:
        st.warning("No text could be extracted from this document.")
        return

    st.caption(f"Preview from {len(records)} extracted text chunk(s)")
    preview = "\n\n".join(record["text"] for record in records)[:PREVIEW_CHAR_LIMIT]
    if sum(len(record["text"]) for record in records) > PREVIEW_CHAR_LIMIT:
        preview += "\n\n[Preview truncated]"
    st.text_area("Extracted text preview", preview, height=500, disabled=True)
    st.caption("PDF locations use physical page numbers; DOCX and text files use text blocks.")


if __name__ == "__main__":
    main()
