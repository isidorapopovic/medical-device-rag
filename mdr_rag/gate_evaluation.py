"""Human labeling of frozen reranker runs, split tuning and held-out evaluation."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool

from .evidence_gate import Calibration, GateContext, GateModel, fingerprint, gate_context, immutable_scorer


class HumanPassageLabel(GateModel):
    id: str = Field(min_length=1)
    relevant: StrictBool
    label_kind: Literal["positive", "negative", "hard_negative"]


class LabelCase(GateModel):
    id: str = Field(min_length=1)
    assessment: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    split: Literal["calibration", "held_out"]
    answerable: StrictBool
    passages: list[HumanPassageLabel]


class ReviewedLabels(GateModel):
    human_validated: Literal[True]
    reviewer: str = Field(min_length=1)
    cases: list[LabelCase] = Field(min_length=1)


def load_labeled_runs(path):
    """Read scores from canonical snapshots, never from hand-entered label scores."""
    from .report_state import decode_state
    labels_path = Path(path).resolve()
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("human_validated") is not True or not str(payload.get("reviewer", "")).strip():
        raise ValueError("Gate labels require explicit human_validated=true and a named reviewer; examples are not calibration")
    try:
        payload = ReviewedLabels.model_validate(payload).model_dump()
    except ValueError as exc:
        raise ValueError("Malformed gate labels; use boolean relevance, split IDs and complete passage labels without hand-entered scores") from exc
    cases, context = [], None
    for row in payload["cases"]:
        run_path = Path(row["assessment"])
        if not run_path.is_absolute():
            run_path = labels_path.parent / run_path
        raw = run_path.read_bytes()
        state = decode_state(json.loads(raw))
        if row["requirement_id"] not in state.sections:
            raise ValueError("Unknown requirement ID in labeled snapshot")
        section = state.sections[row["requirement_id"]]
        try:
            actual = gate_context(state.config, state.corpus_fingerprint, state.device_profile)
        except KeyError as exc:
            raise ValueError("Saved run predates the gate calibration context; collect a new scored assessment without rebuilding the index") from exc
        if context is not None and context != actual:
            raise ValueError("Label cases mix corpus, profile, retrieval or scorer identities; calibrate each context separately")
        context = actual
        trace = section.retrieval_trace
        if trace is None or trace.get("corpus_size") == 0:
            raise ValueError("Label run lacks validated retrieval or has an empty indexed corpus")
        diagnostics = trace.get("reranker")
        scored = diagnostics["scores"] if diagnostics else []
        if diagnostics:
            if diagnostics["identity"] != context.reranker_identity:
                raise ValueError("Saved scores do not match run scorer identity")
            calls = [call for call in section.model_calls if call.outcome == "completed" and call.rerank == diagnostics]
            if len(calls) != 1:
                raise ValueError("Calibration requires exactly one completed bound reranker call")
        elif trace["merged_ids"]:
            raise ValueError("Candidate scores are absent; backend failures cannot be labeled as insufficiency")
        label_rows = row["passages"]
        if len({p["id"] for p in label_rows}) != len(label_rows) or {p["id"] for p in label_rows} != {p["id"] for p in scored}:
            raise ValueError("Human labels must cover every scored candidate exactly once; no implicit negatives")
        by_id = {p["id"]: p for p in label_rows}
        observations = []
        for score in scored:
            label = by_id[score["id"]]
            if type(label["relevant"]) is not bool or label["label_kind"] not in {"positive", "negative", "hard_negative"}:
                raise ValueError("Relevance labels require booleans and positive/negative/hard_negative kinds")
            if label["relevant"] != (label["label_kind"] == "positive"):
                raise ValueError("Label kind and relevance disagree")
            matched = [state.source_buffer[p.buffer_id] for p in calls[0].presented
                       if state.source_buffer[p.buffer_id].chunk_id == score["id"]]
            if len(matched) != 1 or matched[0].kind != "device":
                raise ValueError("Score has no unique device source snapshot")
            observations.append({"id": score["id"], "score": score["score"], "relevant": label["relevant"],
                "label_kind": label["label_kind"], "text_sha256": matched[0].text_sha256,
                "file_sha256": matched[0].file_sha256, "buffer_id": matched[0].buffer_id})
        if type(row["answerable"]) is not bool or row["split"] not in {"calibration", "held_out"}:
            raise ValueError("Each case needs boolean answerable and calibration/held_out split")
        if not row["answerable"] and any(p["relevant"] for p in observations):
            raise ValueError("Unanswerable case cannot contain a human-positive passage")
        cases.append({"id": row["id"], "split": row["split"], "answerable": row["answerable"],
            "query_fingerprint": fingerprint(" ".join(section.queries[0].split()).casefold()),
            "run_fingerprint": fingerprint(json.loads(raw)), "state_revision": state.revision,
            "requirement_id": section.requirement.id, "passages": observations})
    return context, cases, payload["reviewer"], fingerprint(cases)


def validate_cases(cases, *, require_both_splits=True):
    ids, queries = [c["id"] for c in cases], [c["query_fingerprint"] for c in cases]
    if any(not isinstance(key, str) or not key.strip() for key in ids) or len(ids) != len(set(ids)) or len(queries) != len(set(queries)):
        raise ValueError("Cases and questions must be distinct; duplicate/leaking queries cannot tune or validate")
    splits = ("calibration", "held_out") if require_both_splits else ("held_out",)
    for split in splits:
        rows = [c for c in cases if c["split"] == split]
        if {c["answerable"] for c in rows} != {True, False}:
            raise ValueError(f"{split} needs both answerable and unanswerable questions")
        kinds = {p["label_kind"] for c in rows for p in c["passages"]}
        if not {"positive", "hard_negative"} <= kinds:
            raise ValueError(f"{split} needs human-positive passages and hard negatives")
        if any(not math.isfinite(p["score"]) for c in rows for p in c["passages"]):
            raise ValueError("All calibration scores must be finite")


def metrics(cases, threshold):
    tp = fp = fn = tn = correct_answerable = correct_unanswerable = false_accept = 0
    decisions = []
    for case in cases:
        accepted = [p["id"] for p in case["passages"] if p["score"] >= threshold]
        for passage in case["passages"]:
            passes = passage["score"] >= threshold
            tp += int(passes and passage["relevant"])
            fp += int(passes and not passage["relevant"])
            fn += int(not passes and passage["relevant"])
            tn += int(not passes and not passage["relevant"])
        hit = any(p["relevant"] and p["id"] in accepted for p in case["passages"])
        correct_answerable += int(case["answerable"] and hit)
        correct_unanswerable += int(not case["answerable"] and not accepted)
        false_accept += int(not case["answerable"] and bool(accepted))
        decisions.append({"id": case["id"], "answerable": case["answerable"], "accepted_ids": accepted,
                          "abstained": not accepted, "positive_passage_retained": hit})
    positive_cases = sum(c["answerable"] for c in cases)
    negative_cases = len(cases) - positive_cases
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    answerable_recall = correct_answerable / positive_cases if positive_cases else 0.0
    specificity = correct_unanswerable / negative_cases if negative_cases else 0.0
    return {"questions": len(cases), "answerable_questions": positive_cases, "unanswerable_questions": negative_cases,
        "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
        "passage_precision": precision, "passage_recall": recall,
        "passage_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "answerable_hit_rate": answerable_recall, "unanswerable_abstention_rate": specificity,
        "unanswerable_false_accept_rate": false_accept / negative_cases if negative_cases else 0.0,
        "balanced_question_accuracy": (answerable_recall + specificity) / 2, "per_case": decisions}


def tune(context, cases, reviewer, labels_fingerprint):
    """Tune only the calibration split. Held-out scores cannot select threshold."""
    context = GateContext.model_validate(context)
    if not immutable_scorer(context.reranker_identity):
        raise ValueError("Strict calibration requires pinned scorer identity; RRF, distances and mutable Ollama tags are unsupported")
    validate_cases(cases)
    training = [c for c in cases if c["split"] == "calibration"]
    held_out = [c for c in cases if c["split"] == "held_out"]
    thresholds = sorted({float(p["score"]) for c in training for p in c["passages"]})
    above = math.nextafter(max(thresholds), math.inf)
    if math.isfinite(above):
        thresholds.append(above)
    scored = [(metrics(training, threshold), threshold) for threshold in thresholds]
    chosen_metrics, threshold = max(scored, key=lambda pair: (
        pair[0]["balanced_question_accuracy"], pair[0]["passage_f1"], pair[1]))
    chosen_metrics["query_fingerprints"] = [c["query_fingerprint"] for c in training]
    identity = context.reranker_identity
    artifact = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "human_validated": True, "reviewer": reviewer, "model": identity["model"], "revision": identity.get("revision"),
        "score_transformation": identity["score_transformation"], "context": context.model_dump(),
        "labels_fingerprint": labels_fingerprint, "selected_threshold": threshold,
        "objective": "maximize_balanced_question_accuracy_then_passage_f1_then_higher_threshold",
        "calibration_case_ids": [c["id"] for c in training], "held_out_case_ids": [c["id"] for c in held_out],
        "calibration_metrics": chosen_metrics, "validation_metrics": metrics(held_out, threshold)}
    artifact["fingerprint"] = fingerprint(artifact)
    return Calibration.model_validate(artifact)


def calibrate_labels(labels_path, destination):
    from .report_state import atomic_write, exclusive_lock
    context, cases, reviewer, labels_hash = load_labeled_runs(labels_path)
    artifact = tune(context, cases, reviewer, labels_hash)
    destination = Path(destination)
    with exclusive_lock(destination.with_suffix(destination.suffix + ".lock")):
        if destination.exists():
            raise FileExistsError("Calibration artifact already exists; choose a distinct filename to preserve its audit history")
        atomic_write(destination, artifact.model_dump_json(indent=2))
    print(f"Calibration saved to {destination}; held-out metrics do not establish legal confidence")
    return artifact


def evaluate_labels(labels_path, calibration_path, destination):
    from .report_state import atomic_write
    calibration = Calibration.model_validate_json(Path(calibration_path).read_text())
    context, cases, reviewer, labels_hash = load_labeled_runs(labels_path)
    if calibration.context != context:
        raise ValueError("Calibration mismatch; evaluation cannot reuse this threshold")
    held_out = [c for c in cases if c["split"] == "held_out"]
    validate_cases(held_out, require_both_splits=False)
    if set(c["id"] for c in held_out) & set(calibration.calibration_case_ids):
        raise ValueError("Calibration cases cannot be used as held-out evaluation")
    # The training question hashes are retained independently of file paths/IDs.
    original_training_queries = calibration.calibration_metrics.get("query_fingerprints", [])
    if set(c["query_fingerprint"] for c in held_out) & set(original_training_queries):
        raise ValueError("Training question reused under a different held-out ID")
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "calibration_fingerprint": calibration.fingerprint,
        "context": context.model_dump(), "labels_fingerprint": labels_hash, "reviewer": reviewer,
        "threshold": calibration.selected_threshold, "metrics": metrics(held_out, calibration.selected_threshold),
        "interpretation": "Held-out passage relevance and abstention only, not semantic coverage, legal confidence or compliance"}
    atomic_write(Path(destination), json.dumps(report, indent=2))
    print(f"Held-out evidence gate evaluation saved to {destination}")
    return report
