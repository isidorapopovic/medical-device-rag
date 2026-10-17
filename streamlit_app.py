"""Local Streamlit interface for managing and previewing RAG source documents."""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from mdr_rag.core import DOCS, ROOT, source_records
from mdr_rag.app_services import get_index_status, index_documents, get_question_context, ask_question
from mdr_rag.document_ui import SUPPORTED_EXTENSIONS, ingest_uploaded_document
from mdr_rag.ingestion import confined, extraction_warnings

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PREVIEW_CHAR_LIMIT = 12_000
SUPPORTED_TYPES = sorted(extension.lstrip(".") for extension in SUPPORTED_EXTENSIONS)
load_dotenv(ROOT / ".env")


def render_question_controls() -> None:
    st.header("Ask Questions")
    st.caption("Answers use only your selected indexed documents and local Ollama. "
               "Uploaded legal documents may be outdated; this is not a compliance decision.")
    context = get_question_context()
    if context.error:
        st.warning(context.error)
    # Reset the default selection when the index changes, without regenerating an answer.
    if st.session_state.get("question_index_version") != context.index_version:
        st.session_state["question_sources"] = list(context.sources)
        st.session_state["question_index_version"] = context.index_version
        st.session_state.pop("question_result", None)
    scope = st.radio("Source collections", ["All documents", "Legal only", "Device only"], horizontal=True)
    options = [source for source in context.sources if scope == "All documents" or
               source.startswith("legal/" if scope == "Legal only" else "device/")]
    if st.session_state.get("question_collection_scope") != scope:
        st.session_state["question_sources"] = options
        st.session_state["question_collection_scope"] = scope
    selected = st.multiselect("Indexed documents", options=options, key="question_sources",
                             format_func=lambda source: source.replace("legal/", "Legal / ", 1)
                             if source.startswith("legal/") else source.replace("device/", "Device / ", 1),
                             disabled=bool(context.error))
    if not selected:
        st.info("Select at least one indexed document to ask a question.")
    with st.form("ask_question_form"):
        question = st.text_area("Question", key="single_question", max_chars=4000)
        submitted = st.form_submit_button("Ask", disabled=bool(context.error) or not selected)
    view_key = (context.index_version, tuple(sorted(selected)))
    if submitted:
        with st.spinner("Retrieving selected documents and checking the answer…"):
            result = ask_question(question, selected_sources=set(selected))
        st.session_state["question_result"] = (view_key, result)
    saved = st.session_state.get("question_result")
    if not saved or saved[0] != view_key or context.error:
        return
    result = saved[1]
    st.caption(f"Question: {result.question}")
    if result.status == "supported":
        st.success("Supported — citation spans checked and support reviewed by the local model")
        st.write(result.answer)
        st.subheader("Verified cited sources")
        for source in result.sources:
            place = f"PDF page {source.page}" if source.page else f"text block {source.block} (no stable page number)"
            with st.expander(f"{source.source} — {place} — {source.id}"):
                st.caption(f"Source ID: {source.id}")
                st.text(source.excerpt)
    elif result.status in {"insufficient_evidence", "verification_failed"}:
        st.warning("Insufficient evidence" if result.status == "insufficient_evidence" else
                   "Insufficient evidence — answer verification did not pass")
        st.write(result.answer)
    if result.error:
        st.error(result.error)
    for limitation in result.limitations:
        st.caption(limitation)


def render_index_controls() -> None:
    status = get_index_status()
    if message := st.session_state.pop("index_success", None):
        st.success(message)
    label = status.state
    reason = status.reason
    if label == "Not indexed" and st.session_state.get("documents_saved"):
        label = "Index out of date"
        reason = "Documents were saved and have not been indexed. Click Index Documents."
    st.subheader(f"Index status: {label}")
    st.caption(reason)
    st.caption(
        f"Last indexed: {status.indexed_at or 'Never'} | Indexed files: {status.file_count} | "
        f"Chunks: {status.chunk_count} | Embedding model: {status.embedding_model}"
    )
    for warning in status.warnings:
        st.warning(warning)
    if not status.can_index:
        st.info("Save at least one readable supported document. Unreadable legal sources must be replaced or OCR processed.")
    if st.button("Index Documents", disabled=not status.can_index):
        with st.spinner("Indexing legal and device documents with the local embedding model…"):
            result = index_documents()
        if result.success:
            st.session_state["documents_saved"] = False
            st.session_state["index_success"] = (
                f"Indexed {result.status.chunk_count} chunks from {result.status.file_count} files."
            )
            st.rerun()
        else:
            st.error(result.error)


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
    st.caption("Upload, index, preview and ask questions about local legal and device source documents.")
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
                    st.session_state["documents_saved"] = True
                    st.success(f"Saved {saved_path.relative_to(DOCS)}")
                    st.caption("Saved documents require indexing before they are searchable.")
                    st.caption(f"Archived revision {ingested.document.version}; status: {ingested.extraction.status}; manifest: {manifest_hash}")
                    for warning in extraction_warnings(ingested):
                        st.warning(warning)

    st.header("Documents")
    legal_documents = list_documents("legal")
    device_documents = list_documents("device")
    summary_left, summary_right = st.columns(2)
    summary_left.metric("Legal / regulatory files", len(legal_documents))
    summary_right.metric("Device files", len(device_documents))
    render_index_controls()
    render_question_controls()
    st.subheader("Document preview")

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
