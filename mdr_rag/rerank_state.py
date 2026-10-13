"""Version-compatible validation of persisted reranker diagnostics."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoredSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    score: float = Field(allow_inf_nan=False)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    query_start: int | None = None
    query_end: int | None = None
    passage_truncated: bool | None
    query_truncated: bool | None
    token_count: int | None = Field(default=None, ge=1, le=512)
    encoded_sha256: str | None = None
    visibility: Literal["token_offset_envelope", "submitted_text_token_visibility_unverified"]

    @model_validator(mode="after")
    def valid_range(self):
        if self.start >= self.end:
            raise ValueError("Invalid reranker character coverage")
        return self


class RerankDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["none", "llm", "cross_encoder"]
    identity: dict | None = None
    query: str | None = None
    query_sha256: str | None = None
    scores: list[ScoredSpan] = Field(default_factory=list, max_length=30)
    inputs: list[dict] | None = Field(default=None, max_length=30)
    batch_size: int | None = Field(default=None, ge=1, le=4)
    max_tokens: int | None = Field(default=None, ge=32, le=512)
    elapsed_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique_scores(self):
        if len({score.id for score in self.scores}) != len(self.scores):
            raise ValueError("Duplicate reranker score IDs")
        if self.backend == "cross_encoder":
            if not self.identity or self.identity.get("device") != "cpu" or self.identity.get("dtype") != "float32":
                raise ValueError("Cross-encoder diagnostics require CPU float32 identity")
            if self.max_tokens is None or self.batch_size is None:
                raise ValueError("Cross-encoder diagnostics require token and batch limits")
            if any(score.token_count is None or score.encoded_sha256 is None or
                   score.token_count > self.max_tokens for score in self.scores):
                raise ValueError("Cross-encoder score requires bounded traced token inputs")
        return self
