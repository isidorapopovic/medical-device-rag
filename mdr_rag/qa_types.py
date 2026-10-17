"""Presentation-neutral results for the single-turn source-grounded Q&A workflow."""
from dataclasses import dataclass, field
from typing import Literal

DEFAULT_LIMITATIONS = (
    "Uploaded legal documents may be outdated. This answer is not a compliance decision.",
    "Citation spans are checked against source text; semantic support is reviewed by a local model, not a human.",
)


@dataclass(frozen=True)
class AnswerSource:
    id: str
    source: str
    page: int
    block: int
    excerpt: str


@dataclass(frozen=True)
class AnswerResult:
    question: str
    answer: str = ""
    status: Literal["supported", "insufficient_evidence", "verification_failed", "index_invalid",
                    "invalid_selection", "invalid_question", "error"] = "insufficient_evidence"
    sources: tuple[AnswerSource, ...] = ()
    limitations: tuple[str, ...] = DEFAULT_LIMITATIONS
    metadata: dict = field(default_factory=dict)
    error: str | None = None
