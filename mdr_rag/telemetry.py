"""A closed event vocabulary: arbitrary strings and exception text cannot be logged."""
import hashlib
import json
import logging
import re
from uuid import UUID


ERROR_CODES = {"validation_error", "parsing_error", "missing_model", "transient_model_error", "budget_exceeded",
               "citation_error", "missing_evidence", "cancelled", "circuit_open", "storage_error", "execution_error"}
STAGES = {"generation", "embedding", "rerank", "run", "ocr", "ingestion"}


def project_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def emit(run_id: str, project_id_hash: str, stage: str, *, outcome: str, elapsed_ms: int = 0,
         error_code: str | None = None, source_counts: int = 0, usage: dict | None = None,
         logger: logging.Logger | None = None) -> None:
    UUID(run_id)
    if not re.fullmatch(r"[a-f0-9]{64}", project_id_hash):
        raise ValueError("Invalid correlation hash")
    if stage not in STAGES or outcome not in {"started", "completed", "blocked", "failed", "retry"}:
        raise ValueError("Invalid event vocabulary")
    if error_code is not None and error_code not in ERROR_CODES:
        raise ValueError("Invalid error code")
    if type(elapsed_ms) is not int or elapsed_ms < 0 or type(source_counts) is not int or source_counts < 0:
        raise ValueError("Invalid event counts")
    safe_usage = {}
    for key, value in (usage or {}).items():
        if key in {"calls", "input_tokens", "output_tokens", "estimated"} and type(value) in {int, bool} and value >= 0:
            safe_usage[key] = value
    event = dict(run_id=run_id, project_id_hash=project_id_hash, stage=stage, outcome=outcome,
                 elapsed_ms=elapsed_ms, error_code=error_code, source_counts=source_counts, usage=safe_usage)
    (logger or logging.getLogger("mdr_rag.telemetry")).info(json.dumps(event, separators=(",", ":")))
