"""Shared local indexing operations and verified Streamlit status (no shell calls)."""
from dataclasses import dataclass
import logging
import os

from . import core, pipeline, search
from .qa_types import AnswerResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexStatus:
    state: str
    reason: str
    file_count: int = 0
    chunk_count: int = 0
    indexed_at: str | None = None
    embedding_model: str = ""
    warnings: tuple[str, ...] = ()
    can_index: bool = False


@dataclass(frozen=True)
class IndexResult:
    success: bool
    status: IndexStatus
    error: str | None = None


@dataclass(frozen=True)
class QuestionContext:
    sources: tuple[str, ...] = ()
    index_version: str = ""
    error: str | None = None


def get_question_context() -> QuestionContext:
    """Offer only documents from a currently verified index manifest."""
    try:
        status = get_index_status()
        if status.state != "Ready":
            return QuestionContext(error=f"{status.state}: {status.reason}")
        audit = pipeline.check_manifest()
        return QuestionContext(tuple(item["source"] for item in audit["files"]),
                               search.index_fingerprint(audit["files"], audit["embedding_model"]) +
                               ":" + audit.get("indexed_at_utc", ""))
    except Exception:
        logger.exception("Could not load question source selection")
        return QuestionContext(error="Index could not be verified. Rebuild it in Documents before asking.")


def ask_question(question: str, selected_sources: set[str] | None = None, k: int = 5,
                 *, retrieval_query: str | None = None) -> AnswerResult:
    """UI boundary around the shared CLI/Q&A engine with safe, actionable errors."""
    context = get_question_context()
    if context.error:
        return AnswerResult(question, status="index_invalid", error=context.error)
    selection = set(context.sources) if selected_sources is None else set(selected_sources)
    if not selection or not selection <= set(context.sources):
        return AnswerResult(question, status="invalid_selection",
                            error="Select at least one document from the current index.")
    try:
        return pipeline.ask_question(question, selected_sources=selection, k=k,
                                     **({"retrieval_query": retrieval_query} if retrieval_query else {}))
    except Exception as exc:
        from .errors import ParsingError, MissingModel
        from pydantic import ValidationError
        logger.exception("Question answering failed")
        if isinstance(exc, (ParsingError, ValidationError)):
            message = "The local model returned an invalid structured answer. Retry or check the configured chat model."
        elif isinstance(exc, MissingModel):
            message = "A configured Ollama model is missing. Install the chat and embedding models in .env, then retry."
        else:
            message = ("Could not complete the question. Check that Ollama is running, the configured chat and "
                       "embedding models are installed, and local storage is writable, then retry. "
                       "Developer logs contain details.")
        return AnswerResult(question, status="error", error=message)


def get_index_status() -> IndexStatus:
    """Check working bytes, archived provenance, and the active Chroma collection.

    Extraction is local and reuses the existing ingestion archive; no embedding or
    model inference takes place until index_documents is explicitly called.
    """
    model = os.getenv("EMBEDDING_MODEL", "embeddinggemma")
    warnings = []
    can_index = False
    inspected = False
    try:
        records, warnings, files = core.all_records()
        inspected = True
        for item in files:
            if item["chunks"] == 0:
                warnings.append(
                    f"{item['source']}: no readable text. Scanned PDFs need OCR; "
                    "provide a text-readable copy before indexing."
                )
        can_index = bool(records) and not any(
            item["kind"] == "legal" and item["chunks"] == 0 for item in files
        )
    except Exception:
        logger.exception("Could not inspect source documents")
        warnings.append("Could not read source documents. Check file permissions and replace damaged files.")

    audit = {}
    state, reason = "Not indexed", "No index manifest exists. Save documents and click Index Documents."
    path = pipeline.STATE / "manifest.json"
    if path.exists():
        state = "Index out of date"
        try:
            audit = pipeline.load_json(path)
            pipeline.check_manifest()
            if not inspected:
                raise RuntimeError("Source inspection failed. Check document warnings before rebuilding.")
            active = search.collection()
            expected = sum(item["chunks"] for item in audit["files"])
            metadata = active.metadata or {}
            if (expected <= 0 or active.count() != expected
                    or metadata.get("embedding_model") != model
                    or metadata.get("index_fingerprint") != search.index_fingerprint(audit["files"], model)):
                raise RuntimeError("Collection is incomplete or does not match the manifest; rebuild index.")
            state, reason = "Ready", "Saved documents match the verified index."
        except RuntimeError as exc:
            # These are controlled validation messages, not provider exceptions.
            reason = str(exc)
        except Exception:
            logger.exception("Index validation failed")
            reason = "Index could not be verified. Click Index Documents to rebuild; check local storage if this persists."
    # Treat malformed legacy audits as stale, without crashing the document UI.
    try:
        return IndexStatus(
            state, reason, len(audit.get("files", [])),
            sum(item["chunks"] for item in audit.get("files", [])),
            audit.get("indexed_at_utc"), audit.get("embedding_model", model),
            tuple(dict.fromkeys([*audit.get("warnings", []), *warnings])), can_index,
        )
    except (TypeError, KeyError, AttributeError):
        return IndexStatus("Index out of date", "Invalid manifest. Click Index Documents to rebuild.",
                           embedding_model=model, warnings=tuple(warnings), can_index=can_index)


def index_documents() -> IndexResult:
    """Index both source folders through the same guarded implementation as CLI."""
    try:
        pipeline.run_index()
        status = get_index_status()
        if status.state != "Ready":
            raise RuntimeError("Index verification failed after rebuild")
        return IndexResult(True, status)
    except Exception:
        logger.exception("Document indexing failed")
        return IndexResult(False, get_index_status(),
                           "Indexing failed. Check that Ollama is running and the configured embedding "
                           "model is installed, review document warnings and local disk permissions, "
                           "then click Index Documents to retry. Developer logs contain details.")
