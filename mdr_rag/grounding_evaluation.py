"""Offline human adjudication of frozen published claims, never model gold."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from . import pipeline
from .report_state import StateStore, decode_state, fingerprint, atomic_write
from .claim_audit import exact_inventory
from .experiments import public_claim_id


class ClaimLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    verdict: Literal["supported", "contradicted", "insufficient"]
    contradiction_missed: StrictBool


class CaseLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str
    assessment_id: str
    state_revision: int = Field(ge=1)
    state_fingerprint: str
    claim_revision: str
    context_hash: str
    claims: list[ClaimLabel]


class Adjudications(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    dataset_type: Literal["human_gold", "synthetic"]
    human_validated: StrictBool
    reviewer: str = Field(min_length=1)
    evaluation_fingerprint: str
    cases: list[CaseLabel] = Field(min_length=1)


def adjudicate(evaluation_path, labels_path, destination):
    report = json.loads(Path(evaluation_path).read_text(encoding="utf-8"))
    if report.get("fingerprint") != fingerprint({k: v for k, v in report.items() if k != "fingerprint"}):
        raise ValueError("Evaluation artifact fingerprint mismatch")
    labels = Adjudications.model_validate_json(Path(labels_path).read_text(encoding="utf-8"))
    if labels.evaluation_fingerprint != report["fingerprint"]:
        raise ValueError("Adjudications refer to another evaluation")
    if labels.dataset_type == "human_gold" and not labels.human_validated:
        raise ValueError("Human adjudications require explicit validation")
    if labels.dataset_type == "synthetic" and labels.human_validated:
        raise ValueError("Synthetic labels cannot claim human validation")
    if labels.dataset_type != report["dataset"]["dataset_type"]:
        raise ValueError("Adjudication dataset type differs from evaluation; no synthetic-to-human promotion")
    rows = [r for r in report["per_query"] if r.get("assessment_id") and r["outcome"] == "completed"]
    expected = {(r["query_id"], r["assessment_id"]): r for r in rows if r.get("claim_ids")}
    actual = [(c.query_id, c.assessment_id) for c in labels.cases]
    if not exact_inventory(expected, actual):
        raise ValueError("Label every published claim case exactly once; omitted/duplicate/invented cases are invalid")
    results = []
    for label in labels.cases:
        row = expected[(label.query_id, label.assessment_id)]
        for key in ("state_revision", "state_fingerprint", "claim_revision", "context_hash"):
            if getattr(label, key) != row[key]:
                raise ValueError("Claim adjudication revision/source-context binding mismatch")
        store = StateStore(pipeline.STATE, label.assessment_id)
        snapshot = store.directory / "revisions" / f"{label.state_revision:08d}.json"
        state = decode_state(json.loads(snapshot.read_text(encoding="utf-8")))
        if state.revision != label.state_revision or fingerprint(state.model_dump()) != label.state_fingerprint:
            raise ValueError("Frozen assessment differs from the adjudicated snapshot")
        section = state.sections[row["requirement_id"]]
        claims = [public_claim_id(c.claim_id) for c in section.finding.claims]
        if not exact_inventory(claims, [c.claim_id for c in label.claims]) or claims != row["claim_ids"]:
            raise ValueError("Human claim labels must cover the exact published inventory")
        results.append({"query_id": label.query_id, "assessment_id": label.assessment_id,
            "claims": len(claims), "supported": sum(c.verdict == "supported" for c in label.claims),
            "contradicted": sum(c.verdict == "contradicted" for c in label.claims),
            "insufficient": sum(c.verdict == "insufficient" for c in label.claims),
            "contradiction_misses": sum(c.contradiction_missed for c in label.claims)})
    count = sum(r["claims"] for r in results)
    output = {"schema_version": 1, "evaluation_fingerprint": report["fingerprint"],
        "labels_fingerprint": fingerprint(labels.model_dump()), "dataset_type": labels.dataset_type,
        "human_validated": labels.human_validated, "reviewer": labels.reviewer,
        "cases": len(results), "claims": count,
        "claim_support_precision": sum(r["supported"] for r in results) / count if count else None,
        "contradiction_misses": sum(r["contradiction_misses"] for r in results), "per_case": results,
        "limitations": "Published-claim adjudication only: withheld drafts and absent claims are excluded. Small samples are exploratory."}
    if Path(destination).exists():
        raise FileExistsError("Grounding output exists; choose a new filename")
    atomic_write(Path(destination), json.dumps(output, ensure_ascii=False, indent=2))
    return output
