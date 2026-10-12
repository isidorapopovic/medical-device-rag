"""Local document upload helpers shared by the Streamlit interface and tests."""
from pathlib import Path

from .core import DOCS

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

    name = Path(filename).name
    if not name or name in {".", ".."} or "\x00" in name:
        raise ValueError("Invalid upload filename")
    if Path(name).suffix.casefold() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Supported file types are PDF, DOCX, TXT and MD")

    folder = documents_root / kind
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / name
    try:
        with destination.open("xb") as uploaded_file:
            uploaded_file.write(content)
    except FileExistsError as exc:
        raise FileExistsError(
            f"{kind}/{name} already exists; rename the upload to avoid overwriting it"
        ) from exc
    return destination
