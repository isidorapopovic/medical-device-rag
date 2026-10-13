"""Persistable diagnostics, separate from model presentation and citations."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BackendHit(TraceModel):
    query_id: str
    query: str
    backend: Literal["dense", "bm25"]
    backend_rank: int = Field(ge=1, le=12)
    query_rank: int = Field(ge=1, le=24)


class CandidateTrace(TraceModel):
    id: str
    fusion_score: float = Field(gt=0, allow_inf_nan=False)
    provenance: list[BackendHit] = Field(min_length=1, max_length=8)


class QueryTrace(TraceModel):
    query_id: str
    query: str
    candidate_ids: list[str] = Field(max_length=24)


class RetrievalTrace(TraceModel):
    queries: list[QueryTrace] = Field(min_length=1, max_length=4)
    candidates: list[CandidateTrace] = Field(max_length=96)
    merged_ids: list[str] = Field(max_length=30)
    selected_ids: list[str] = Field(max_length=30)
    mode: Literal["dense", "bm25", "hybrid"]
    per_backend: int = Field(ge=1, le=12)
    merged_limit: int = Field(ge=1, le=30)
    reranked: bool

    @model_validator(mode="after")
    def consistent_lists(self):
        ids = [c.id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Candidate IDs must be unique")
        queries = {q.query_id: q for q in self.queries}
        if len(queries) != len(self.queries):
            raise ValueError("Query IDs must be unique")
        for query in self.queries:
            if len(query.candidate_ids) != len(set(query.candidate_ids)) or not set(query.candidate_ids) <= set(ids):
                raise ValueError("Query candidates must be unique known IDs")
        for candidate in self.candidates:
            votes = set()
            for hit in candidate.provenance:
                query = queries.get(hit.query_id)
                if query is None or query.query != hit.query or candidate.id not in query.candidate_ids:
                    raise ValueError("Unknown query provenance")
                if (hit.query_id, hit.backend) in votes or hit.query_rank > len(query.candidate_ids) or query.candidate_ids[hit.query_rank - 1] != candidate.id:
                    raise ValueError("Duplicate vote or wrong query rank")
                votes.add((hit.query_id, hit.backend))
        if len(self.merged_ids) > self.merged_limit or len(self.merged_ids) != len(set(self.merged_ids)):
            raise ValueError("Merged candidate budget exceeded or duplicate IDs")
        if not set(self.merged_ids) <= set(ids) or not set(self.selected_ids) <= set(self.merged_ids):
            raise ValueError("Unknown merged/selected ID")
        if len(self.selected_ids) != len(set(self.selected_ids)):
            raise ValueError("Selected IDs must be unique")
        return self
