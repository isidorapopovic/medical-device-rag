"""Explicit opt-in retrieval recovery; never reinterpret invalid evidence."""
import copy
import sqlite3

from .errors import BudgetExceeded, CircuitOpen, MissingModel, TransientModelError


def recoverable(error: Exception, *, storage: bool = False) -> bool:
    from .reranking import RerankerUnavailable
    permitted = (TimeoutError, ConnectionError, MissingModel, TransientModelError,
                 BudgetExceeded, CircuitOpen, RerankerUnavailable)
    return isinstance(error, permitted) or storage and (
        isinstance(error, (OSError, sqlite3.DatabaseError)) or
        type(error).__module__.startswith("chromadb.errors"))


class RecordCollection:
    """Lexical fallback over a caller-verified immutable snapshot, never a DB repair."""
    def __init__(self, records: list[dict]):
        self.records = copy.deepcopy(records)
        self.id = "verified-lexical-snapshot"
    def get(self, **kwargs):
        rows = [r for r in self.records if r["meta"].get("kind") == kwargs["where"]["kind"]]
        return {"ids": [r["id"] for r in rows], "documents": [r["text"] for r in rows],
                "metadatas": [r["meta"] for r in rows]}


def validate_records(records: dict, expected: list[dict], kind: str) -> dict:
    allowed = {}
    for row in expected:
        if row["id"] in allowed and row != allowed[row["id"]]:
            raise ValueError("Ambiguous expected source identity")
        allowed[row["id"]] = row
    expected_ids = {key for key, row in allowed.items() if row["meta"].get("kind") == kind}
    if set(records) != expected_ids:
        raise ValueError("Indexed source inventory differs from the frozen snapshot")
    valid = {}
    for key, row in records.items():
        reference = allowed.get(key)
        if reference is None or reference["meta"].get("kind") != kind:
            continue
        # Exact metadata equality deliberately fails closed for stale/versioned
        # or cross-project records. Source text is never repaired from the index.
        if row != reference:
            raise ValueError("Indexed source text or provenance differs from the frozen snapshot")
        valid[key] = copy.deepcopy(row)
    return valid
