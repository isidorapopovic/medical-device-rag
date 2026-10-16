"""Local document upload helpers shared by the Streamlit interface and tests."""
from pathlib import Path

from .core import DOCS
from .ingestion import IngestionStore, atomic_bytes, confined, safe_filename
from .document_parsers import MAX_BYTES

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def save_uploaded_document(
    kind: str,
    filename: str,
    content: bytes,
    documents_root: Path = DOCS,
) -> Path:
    """Save an upload below the selected corpus without overwriting existing files."""
    if kind not in {"legal", "device"}:
        raise ValueError("Document type must be 'legal' or 'device'")

    name = safe_filename(filename)
    if Path(name).suffix.casefold() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Supported file types are PDF, DOCX, TXT and MD")

    if len(content) > MAX_BYTES:
        raise ValueError("upload_exceeds_50_mib")
    folder = confined(documents_root, documents_root / kind)
    folder.mkdir(parents=True, exist_ok=True)
    destination = confined(documents_root, folder / name)
    from .report_state import exclusive_lock
    with exclusive_lock(folder / ".upload.lock"):
        if destination.exists():
            raise FileExistsError(f"{kind}/{name} already exists; rename the upload to avoid overwriting it")
        atomic_bytes(destination, content, immutable=True)
    return destination


def ingest_uploaded_document(kind: str, filename: str, content: bytes, *, documents_root: Path = DOCS,
                             archive_root: Path | None = None):
    """Archive original revisions, then atomically publish the latest working copy."""
    from .core import STATE
    if kind not in {"legal", "device"}:
        raise ValueError("Document type must be legal or device")
    name = safe_filename(filename)
    destination = confined(documents_root, documents_root / kind / name)
    archive_root = archive_root or (STATE / "ingestion" if documents_root == DOCS else documents_root / ".ingestion")
    store = IngestionStore(archive_root)
    # Preserve pre-existing working bytes too, even if uploaded before this stage.
    from .report_state import exclusive_lock
    with exclusive_lock(destination.parent / ".upload.lock"):
        if destination.exists():
            if destination.stat().st_size > MAX_BYTES:
                raise ValueError("upload_exceeds_50_mib")
            if destination.read_bytes() != content:
                store.ingest_path(destination, kind, allowed_root=documents_root)
        ingested, manifest_hash = store.ingest(kind, name, content)
        atomic_bytes(destination, content)
    return destination, ingested, manifest_hash
