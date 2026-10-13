"""Passage relevance screening; never sufficiency, conformity or confidence."""
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


class GateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GateContext(GateModel):
    reranker_identity: dict
    retrieval_configuration: dict
    corpus_fingerprint: str
    profile_fingerprint: str
    score_source: Literal["reranker"] = "reranker"
    distance_gate: Literal["not_used"] = "not_used"


def gate_context(config, corpus, profile):
    keys = ("k", "retrieval_mode", "embedding_model", "retrieval_per_query", "retrieval_max_candidates",
            "retrieval_version", "query_version", "multi_query_enabled", "multi_query_max", "query_planner",
            "planner_hash", "rerank_query_version", "retrieval_pool_policy")
    retrieval = {key: config[key] for key in keys}
    if config.get("ollama_gpu_layers") is not None:
        retrieval["ollama_gpu_layers"] = config["ollama_gpu_layers"]
    if config["query_planner"] == "llm":
        retrieval.update(planner_model=config["llm_model"], planner_num_ctx=config["num_ctx"])
    if config["reranker_backend"] == "llm":
        retrieval["reranker_prompt_hash"] = config["reranker_prompt_hash"]
    return GateContext(reranker_identity=config["reranker_identity"], retrieval_configuration=retrieval,
                       corpus_fingerprint=corpus, profile_fingerprint=fingerprint(profile))


class Calibration(GateModel):
    schema_version: Literal[1] = 1
    created_at: str
    human_validated: Literal[True]
    reviewer: str = Field(min_length=1)
    model: str
    revision: str | None
    score_transformation: str
    context: GateContext
    labels_fingerprint: str
    selected_threshold: float = Field(allow_inf_nan=False)
    objective: str
    calibration_case_ids: list[str] = Field(min_length=2)
    held_out_case_ids: list[str] = Field(min_length=2)
    calibration_metrics: dict
    validation_metrics: dict
    fingerprint: str

    @model_validator(mode="after")
    def valid_identity(self):
        identity = self.context.reranker_identity
        if (self.model, self.revision, self.score_transformation) != (
                identity.get("model"), identity.get("revision"), identity.get("score_transformation")):
            raise ValueError("Calibration score/model identity mismatch")
        if set(self.calibration_case_ids) & set(self.held_out_case_ids):
            raise ValueError("Calibration and held-out IDs overlap")
        if self.fingerprint != fingerprint(self.model_dump(exclude={"fingerprint"})):
            raise ValueError("Calibration artifact fingerprint mismatch")
        if not immutable_scorer(identity):
            raise ValueError("Strict calibration requires a pinned scorer; mutable Ollama tags are insufficient")
        return self


def immutable_scorer(identity):
    return (identity.get("backend") == "cross_encoder" and bool(identity.get("revision")) and
            bool(identity.get("fingerprint")) and bool(identity.get("artifacts_sha256"))) or (
            identity.get("backend") == "llm" and bool(identity.get("model_digest")))


def settings():
    mode = os.getenv("EVIDENCE_GATE_MODE", "strict").lower()
    if mode not in {"strict", "experimental", "disabled"}:
        raise ValueError("EVIDENCE_GATE_MODE must be strict, experimental, or disabled")
    threshold = None
    if mode == "experimental":
        try:
            threshold = float(os.getenv("EVIDENCE_GATE_THRESHOLD", ""))
        except ValueError:
            raise ValueError("Experimental mode requires an explicit finite EVIDENCE_GATE_THRESHOLD; it is not calibrated") from None
        if not math.isfinite(threshold):
            raise ValueError("EVIDENCE_GATE_THRESHOLD must be finite")
    path = os.getenv("EVIDENCE_GATE_CALIBRATION", "").strip()
    calibration = None
    if path and mode == "strict":
        try:
            calibration = Calibration.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RuntimeError("Malformed calibration artifact; preserve it and verify its schema/fingerprint") from exc
    return {"gate_mode": mode, "gate_threshold": threshold,
            "gate_calibration": calibration.model_dump() if calibration else None,
            "calibration": calibration.fingerprint if calibration else None}


class AtomicObligation(GateModel):
    obligation_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    qualifiers: list[str] = Field(default_factory=list)


def obligation_inventory(requirement):
    explicit = getattr(requirement, "atomic_obligations", None)
    rows = explicit if explicit is not None else [{"obligation_id": requirement.id, "text": requirement.requirement,
                                                  "qualifiers": getattr(requirement, "qualifiers", [])}]
    items = [AtomicObligation.model_validate(row) for row in rows]
    if not items or len({row.obligation_id for row in items}) != len(items):
        raise ValueError("Atomic obligation inventory must be nonempty with unique IDs")
    return [row.model_dump() for row in items]


class PassageDecision(GateModel):
    id: str
    score: float | None = Field(default=None, allow_inf_nan=False)
    accepted: bool
    reason: str


class GateDecision(GateModel):
    mode: Literal["strict", "experimental", "disabled"]
    status: Literal["passed", "insufficient_evidence", "disabled"]
    reason: str
    threshold: float | None = Field(default=None, allow_inf_nan=False)
    calibration_fingerprint: str | None = None
    context_fingerprint: str
    strict_validation_passed: bool = False
    accepted_ids: list[str]
    rejected_ids: list[str]
    draft_ids: list[str]
    passages: list[PassageDecision]
    obligations: list[AtomicObligation]
    coverage_verification: Literal["pending", "no_accepted_passages", "model_self_assessed_raw_citations_only"] = "pending"

    @model_validator(mode="after")
    def coherent(self):
        ids = [p.id for p in self.passages]
        if len(ids) != len(set(ids)) or self.accepted_ids != [p.id for p in self.passages if p.accepted] or \
                self.rejected_ids != [p.id for p in self.passages if not p.accepted]:
            raise ValueError("Gate decisions must partition unique candidate IDs")
        if not set(self.draft_ids) <= set(self.accepted_ids) or len(self.draft_ids) != len(set(self.draft_ids)):
            raise ValueError("Draft IDs must be unique accepted IDs")
        if self.strict_validation_passed and (self.mode != "strict" or not self.calibration_fingerprint or self.status != "passed"):
            raise ValueError("Only a calibrated strict pass can be marked validated")
        if self.status == "passed" and (not self.accepted_ids or not self.draft_ids):
            raise ValueError("Passed gate requires retained draft evidence")
        if self.status == "insufficient_evidence" and self.accepted_ids:
            raise ValueError("An abstaining gate cannot have accepted evidence")
        if self.mode != "disabled" and self.accepted_ids:
            if self.threshold is None or any(p.score is None or p.score < self.threshold for p in self.passages if p.accepted):
                raise ValueError("Accepted gate evidence requires a passing finite score")
        if self.mode == "strict" and self.status == "passed" and not self.strict_validation_passed:
            raise ValueError("Strict gate pass requires matched calibration")
        return self


def screen(passages, retrieval_trace, config, context, obligations):
    mode = config["gate_mode"]
    diagnostics = (retrieval_trace or {}).get("reranker") or {}
    scores = {s["id"]: s["score"] for s in diagnostics.get("scores", [])}
    threshold, calibration_id, block = config["gate_threshold"], None, None
    if mode == "strict":
        if config["gate_calibration"] is None:
            block = "threshold_not_calibrated"
        else:
            calibration = Calibration.model_validate(config["gate_calibration"])
            calibration_id = calibration.fingerprint
            if calibration.context != context:
                block = "calibration_mismatch"
            else:
                threshold = calibration.selected_threshold
    if mode != "disabled" and block is None and passages:
        if diagnostics.get("backend") not in {"llm", "cross_encoder"}:
            raise RuntimeError("Evidence gate requires reranker scores; RRF and unverified Chroma distances cannot be thresholded")
        if diagnostics.get("identity") != context.reranker_identity:
            raise RuntimeError("Reranker score identity differs from validated gate context; retry without reusing stale scores")
        if set(scores) != {p.id for p in passages} or len(scores) != len(diagnostics["scores"]):
            raise RuntimeError("Gate requires a complete unique score mapping; scoring failure is not evidence insufficiency")
    decisions = []
    for passage in passages:
        score = scores.get(passage.id)
        if score is not None and (isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score)):
            raise RuntimeError("Invalid reranker score; no evidence finding can be made")
        accepted = mode == "disabled" or (block is None and score is not None and score >= threshold)
        reason = "gate_disabled_not_strictly_validated" if mode == "disabled" else block or (
            "experimental_threshold_pass" if accepted and mode == "experimental" else
            "experimental_threshold_reject" if mode == "experimental" else
            "calibrated_threshold_pass" if accepted else "below_calibrated_threshold")
        decisions.append(PassageDecision(id=passage.id, score=score, accepted=accepted, reason=reason))
    accepted = [p.id for p in decisions if p.accepted]
    status = "disabled" if mode == "disabled" else "passed" if accepted else "insufficient_evidence"
    return GateDecision(mode=mode, status=status,
        reason=block or ("gate_disabled_not_strictly_validated" if mode == "disabled" else
                        "relevant_passages_retained_coverage_unverified" if accepted else "no_passage_passed"),
        threshold=threshold, calibration_fingerprint=calibration_id, context_fingerprint=fingerprint(context.model_dump()),
        strict_validation_passed=mode == "strict" and block is None and bool(accepted),
        accepted_ids=accepted, rejected_ids=[p.id for p in decisions if not p.accepted],
        draft_ids=accepted[:config["k"]], passages=decisions, obligations=obligations,
        coverage_verification="pending" if accepted else "no_accepted_passages")
