"""Production-path comparisons with redacted artifacts and explicit failures."""
import hashlib
import inspect
from importlib.metadata import version, PackageNotFoundError
import json
import math
import os
import platform
import statistics
import time
import tracemalloc
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from . import search, pipeline, review_state
from .core import ROOT, REPORTS
from .evaluation import load_gold, rank_scores
from .query_planner import plan_queries
from .report_state import StateStore, atomic_write, fingerprint, validate_assessment_id
from .reranking import backend_selection, requirement_rerank_query
from . import reranking
from .saved_configuration import scoped_environment

METHODS = ("dense", "bm25", "hybrid", "multi_query_hybrid", "multi_query_cross_encoder",
           "complete_pipeline_cross_encoder", "hybrid_llm", "hybrid_cross_encoder",
           "complete_pipeline_none", "complete_pipeline_llm")
COMPARE = METHODS[:6]


def load_dataset(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = load_gold(path)
    metadata = {"dataset_type": "unverified_legacy", "human_validated": False, "reviewer": None}
    if isinstance(data, dict):
        if (type(data.get("schema_version")) is not int or data["schema_version"] != 1) or data.get("dataset_type") not in {"human_gold", "synthetic", "unverified"}:
            raise ValueError("Dataset requires schema_version=1 and an explicit dataset_type")
        if type(data.get("human_validated")) is not bool:
            raise ValueError("Dataset human_validated must be a JSON boolean")
        if data["dataset_type"] == "human_gold" and (not data["human_validated"] or (not isinstance(data.get("reviewer"), str) or not data["reviewer"].strip())):
            raise ValueError("Human gold requires explicit human validation and reviewer identity")
        if data["dataset_type"] != "human_gold" and data["human_validated"]:
            raise ValueError("Synthetic/unverified data cannot claim human-gold validation")
        metadata = {key: data.get(key) for key in ("dataset_type", "human_validated", "reviewer", "sources_sha256", "legal_version_label")}
        if data["dataset_type"] == "human_gold" and (not isinstance(data.get("sources_sha256"), dict) or not data["sources_sha256"] or (not isinstance(data.get("legal_version_label"), str) or not data["legal_version_label"].strip())):
            raise ValueError("Human gold must pin source hashes and the legal source-version label")
    queries, requirement_ids = set(), set()
    for case in cases:
        key = " ".join(case["query"].split()).casefold()
        if key in queries:
            raise ValueError("Repeated questions cannot receive duplicate votes or cross dataset splits")
        queries.add(key)
        if case.get("requirement_id"):
            if case["requirement_id"] in requirement_ids:
                raise ValueError("An existing requirement cannot receive duplicate votes or cross dataset splits")
            requirement_ids.add(case["requirement_id"])
        if case.get("split", "unspecified") not in {"calibration", "held_out", "unspecified"}:
            raise ValueError("Case split must be calibration, held_out, or unspecified")
        labels = case.get("passage_labels", [])
        if not isinstance(labels, list):
            raise ValueError("passage_labels must be a list")
        seen = set()
        for label in labels:
            if (not isinstance(label, dict) or not isinstance(label.get("chunk_id"), str) or
                    not label["chunk_id"] or type(label.get("relevant")) is not bool or
                    label["chunk_id"] in seen or not isinstance(label.get("source"), str) or
                    not isinstance(label.get("file_sha256"), str) or not label["file_sha256"]):
                raise ValueError("Passage labels require unique chunk IDs, boolean relevance, source and file hash")
            seen.add(label["chunk_id"])
    metadata.update(fingerprint=fingerprint(data), sample_size=len(cases),
        split_counts=dict(Counter(c.get("split", "unspecified") for c in cases)),
        answerable_count=sum(c.get("answerable", True) for c in cases),
        unanswerable_count=sum(not c.get("answerable", True) for c in cases),
        categories=dict(Counter(tag for c in cases for tag in c.get("tags", []))))
    return cases, metadata


def latency_summary(values):
    values = sorted(values)
    return {"samples": len(values), "median_seconds": statistics.median(values) if values else None,
            "p95_seconds": values[max(0, math.ceil(.95 * len(values)) - 1)] if values else None}


def public_claim_id(value):
    return "CL-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def library_versions():
    values = {}
    for name in ("ollama", "chromadb", "pydantic", "rank-bm25", "numpy", "sentence-transformers", "torch"):
        try:
            values[name] = version(name)
        except PackageNotFoundError:
            values[name] = "not_installed"
    return values


def memory_summary():
    current, peak = tracemalloc.get_traced_memory()
    result = {"python_allocation_peak_bytes": peak, "process_rss_bytes": None,
              "process_lifetime_peak_rss_bytes": None,
              "limitations": "Python allocation peak excludes native tensor allocations. Process memory excludes the Ollama server and is not a per-stage peak."}
    try:
        import psutil
        info = psutil.Process().memory_info()
        result.update(process_rss_bytes=info.rss, process_lifetime_peak_rss_bytes=getattr(info, "peak_wset", None))
    except Exception as exc:
        result["measurement_error"] = type(exc).__name__
    return result


def _validate_labels(case, metadata):
    for label in case["relevant"]:
        matches = [key for key, meta in metadata.items() if meta["source"] == label["source"] and
            (label.get("page") is None or meta.get("page") == label["page"]) and
            (label.get("chunk_id") is None or key == label["chunk_id"])]
        if not matches:
            raise ValueError(f"{case['id']}: ground-truth label not in current index")
    for label in case.get("passage_labels", []):
        meta = metadata.get(label["chunk_id"])
        if meta is None or (meta["source"], meta.get("sha256")) != (label["source"], label["file_sha256"]):
            raise ValueError("Passage label hash/identity is stale or absent from corpus")


def _precision(ids, case):
    labels = {l["chunk_id"]: l["relevant"] for l in case.get("passage_labels", [])}
    known = [labels[key] for key in ids if key in labels]
    return {"passage_label_coverage": len(known) / len(ids) if ids else None,
            "passage_relevance_precision": sum(known) / len(known) if known and len(known) == len(ids) else None}


def _queries(case, requirements, profile, multi):
    requirement = requirements.get(case.get("requirement_id"))
    if case.get("requirement_id") and requirement is None:
        raise ValueError("Evaluation references an unknown requirement ID")
    requirement = requirement or SimpleNamespace(provision="", requirement=case["query"], exact_quote="")
    result = plan_queries(requirement, profile, maximum=4 if multi else 1)
    if not case.get("requirement_id"):
        result.queries[0].text = case["query"]
    return [q.text for q in result.queries]


def _review(case, run_id, backend, maximum, profile):
    if case.get("split") != "held_out" or case["kind"] != "device" or not case.get("requirement_id"):
        raise ValueError("Complete pipeline evaluation requires held_out device cases with existing requirement IDs")
    assessment_id = f"eval-{run_id}-{hashlib.sha256((backend + case['id']).encode()).hexdigest()[:10]}"
    overrides = {"retrieval_mode": "hybrid", "multi_query_enabled": True,
                 "multi_query_max": 4, "query_planner": "deterministic", "reranker_backend": backend,
                 "retrieval_per_query": 12, "retrieval_max_candidates": 30}
    try:
        state = pipeline.run_review(assessment_id=assessment_id, requirement_id=None,
                                    limit=None, k=maximum, config_overrides=overrides,
                                    evaluation_requirement_id=case["requirement_id"])
    except Exception:
        # Failed executions remain failed. Never count them as abstentions.
        raise
    section = state.sections[case["requirement_id"]]
    failures = [c for c in section.model_calls if c.outcome == "failed"]
    if failures and section.finding.status == "needs_review":
        raise RuntimeError("Review/repair execution failed; this is not a valid abstention")
    trace = section.retrieval_trace or {"merged_ids": [], "selected_ids": []}
    retained = section.evidence_gate.draft_ids
    finding = section.finding
    audited = section.audit_status == "semantic_checked"
    from .claim_audit import CitationAuditor, exact_inventory
    from .source_buffer import SourceBuffer
    call = next((c for c in section.model_calls if c.call_id == section.draft_call_id), None)
    reference_count, valid_spans = 0, 0
    if call and section.structured_draft:
        auditor = CitationAuditor(SourceBuffer(state.source_buffer), call.presented)
        for claim in section.structured_draft.claims:
            for reference in claim.evidence:
                reference_count += 1
                try:
                    auditor.reference(reference, claim.claim_id)
                    valid_spans += 1
                except ValueError:
                    pass
    claim_ids = [c.claim_id for c in finding.claims] if finding else []
    records = [r for r in section.validation_records if r.get("outcome") == "completed"]
    # Reviewer coverage measures identity inventory only, never human support.
    last = records[-1] if records else None
    reviewed = [c["claim_id"] for c in last["review"]["claims"]] if last else []
    draft_ids = [c.claim_id for c in section.structured_draft.claims] if section.structured_draft else []
    return {"ranked": [p.id for p in section.passages], "candidates": trace["merged_ids"],
        "retained": retained, "trace": trace, "identity": state.config["reranker_identity"],
        "assessment_id": assessment_id, "state_revision": state.revision,
        "state_fingerprint": fingerprint(state.model_dump()), "requirement_id": case["requirement_id"],
        "claim_ids": [public_claim_id(key) for key in claim_ids], "finding_status": finding.status if finding else None,
        "abstained": finding.status in {"insufficient_evidence", "needs_review"} if finding else None,
        "strict_gate_passed": section.evidence_gate.strict_validation_passed,
        "gate_mode": section.evidence_gate.mode, "gate_reason": section.evidence_gate.reason,
        "calibration_fingerprint": section.evidence_gate.calibration_fingerprint,
        "audit_status": section.audit_status, "published_claim_count": len(claim_ids),
        "citation_span_count": reference_count,
        "citation_id_span_validity": valid_spans / reference_count if reference_count else None,
        "published_citation_id_span_validity": 1.0 if audited and section.claim_links else None,
        "reviewer_inventory_valid": exact_inventory(draft_ids, reviewed) if draft_ids else None,
        "reviewer_coverage": len(set(reviewed) & set(draft_ids)) / len(draft_ids) if draft_ids else None,
        "claim_revision": last.get("claim_revision") if last else None,
        "context_hash": last.get("context_hash") if last else None,
        "stage_latencies": [{"stage": e.stage, "outcome": e.outcome, "seconds": e.elapsed_seconds}
            for e in state.events if e.requirement_id == case["requirement_id"] and e.elapsed_seconds is not None],
        "configuration": {k: v for k, v in state.config.items() if k not in {"gate_calibration", "cross_encoder_cache"}},
        "model_call_failures": len(failures), "human_claim_support": None, "contradiction_misses": None}


def evaluate_production(gold_path, ks, destination, include_reranked, *, methods=None, compare_all=False, run_id=None):
    path = Path(gold_path) if gold_path else ROOT / "eval" / "gold_queries.json"
    cases, dataset = load_dataset(path)
    ks = sorted(set(ks))
    if not ks or any(type(k) is not int or not 1 <= k <= 30 for k in ks):
        raise ValueError("Evaluation k values must be integers in 1..30")
    maximum = max(ks)
    explicit_methods = methods is not None
    methods = list(methods) if methods else list(COMPARE if compare_all else METHODS[:3])
    if include_reranked or (include_reranked is None and backend_selection() != "none" and not compare_all and not explicit_methods):
        selected = backend_selection()
        methods.append("hybrid_" + (selected if selected != "none" else "llm"))
    methods = list(dict.fromkeys(methods))
    if any(m not in METHODS for m in methods):
        raise ValueError("Unknown production comparison method")
    run_id = run_id or uuid4().hex[:12]
    validate_assessment_id(run_id)
    if len(run_id) > 48:
        raise ValueError("Evaluation run ID must be at most 48 characters")
    output = Path(destination) if destination else REPORTS / ("evaluation-" + run_id) / "evaluation.json"
    if output.exists() or output.with_suffix(".md").exists():
        raise FileExistsError("Evaluation output already exists; choose a distinct run ID/path")
    manifest = pipeline.check_manifest()
    if dataset["dataset_type"] == "human_gold" and (dataset["sources_sha256"] != {f["source"]: f["sha256"] for f in manifest["files"]} or dataset["legal_version_label"] != os.getenv("LEGAL_VERSION", "UNSPECIFIED HISTORICAL TEXT")):
        raise ValueError("Human gold source/version fingerprints differ from the current corpus")
    corpus = review_state.corpus_hash(manifest)
    requirements = {}
    register = pipeline.STATE / "requirements_draft.json"
    if register.exists():
        from .roles import RequirementAnalyst
        requirements = {r.id: r for r in RequirementAnalyst().register(pipeline.load_json(register)).requirements}
    profile = pipeline.profile_data()
    metadata = {}
    for kind in {case["kind"] for case in cases}:
        data = search.collection().get(where={"kind": kind}, include=["metadatas"])
        metadata[kind] = {key: meta for key, meta in zip(data["ids"], data["metadatas"])
                          if meta.get("kind") == kind and meta.get("source", "").startswith(kind + "/")}
    for case in cases:
        _validate_labels(case, metadata[case["kind"]])
    rows, attempts, excluded = [], [], []
    tracing = tracemalloc.is_tracing()
    if not tracing:
        tracemalloc.start()
    try:
        for method in methods:
            for case in cases:
                if method.startswith("complete_pipeline") and (case.get("split") != "held_out" or case["kind"] != "device" or not case.get("requirement_id")):
                    excluded.append({"query_id": case["id"], "method": method, "reason": "requires_held_out_device_requirement"})
                    continue
                start = time.perf_counter()
                base = {"query_id": case["id"], "method": method, "kind": case["kind"],
                        "answerable": case.get("answerable", True), "split": case.get("split", "unspecified")}
                try:
                    backend = "cross_encoder" if method.endswith("cross_encoder") else "llm" if method.endswith("llm") else "none"
                    multi = method.startswith("multi_query") or method.startswith("complete_pipeline")
                    queries = _queries(case, requirements, profile if case["kind"] == "device" else {}, multi)
                    if method.startswith("complete_pipeline"):
                        result = _review(case, run_id, backend, maximum, profile)
                    else:
                        identity = reranking.reranker_identity(backend)
                        retrieval = search.retrieve_candidates(queries, case["kind"], k=30,
                            mode=method if method in {"dense", "bm25"} else "hybrid", backend=backend,
                            rerank_query=requirement_rerank_query(queries[0], profile if case["kind"] == "device" else {}),
                            manifest_fingerprint=corpus, per_backend=12, merged_limit=30)
                        if retrieval["trace"]["corpus_size"] == 0:
                            raise RuntimeError("Indexed corpus is empty; this is an execution failure")
                        result = {"ranked": [p["id"] for p in retrieval["passages"]],
                                  "candidates": retrieval["trace"]["merged_ids"], "trace": retrieval["trace"],
                                  "identity": identity, "retained": None, "abstained": None}
                    trace = result.pop("trace")
                    elapsed = time.perf_counter() - start
                    diagnostics = trace.get("reranker") or {}
                    stages = result.pop("stage_latencies", [{"stage": "retrieval_and_rerank", "outcome": "completed", "seconds": elapsed}])
                    attempts.append({**base, "outcome": "completed", "elapsed_seconds": elapsed, "model_call_failures": result.get("model_call_failures", 0), "stages": stages})
                    candidates = result.pop("candidates")
                    ranked = result.pop("ranked")
                    retained = result.pop("retained")
                    provenance = [{"id": c["id"], "provenance": [{key: value for key, value in p.items() if key != "query"}
                        for p in c["provenance"]]} for c in trace.get("candidates", [])]
                    common = {**base, **result, "outcome": "completed", "candidate_recall": rank_scores(candidates, metadata[case["kind"]], case["relevant"], 30)["recall"],
                        "candidate_ids": candidates, "provenance": provenance, "retrieval_mode": trace["mode"], "backend": backend,
                        "parameters": {"per_query_backend": 12, "merged_candidates": 30, "query_count": len(queries),
                                       "query_fingerprints": [fingerprint(q) for q in queries], "max_queries": 4 if multi else 1},
                        "rerank_scores": [{k: v for k, v in score.items() if k != "query"} for score in diagnostics.get("scores", [])],
                        "elapsed_seconds": elapsed, "rerank_elapsed_seconds": diagnostics.get("elapsed_seconds")}
                    for k in ks:
                        metric = rank_scores(ranked, metadata[case["kind"]], case["relevant"], k)
                        output_ids = retained if retained is not None else ranked[:k]
                        retention = rank_scores(output_ids, metadata[case["kind"]], case["relevant"], max(1, len(output_ids)))["hit_rate"] if case.get("answerable", True) else None
                        rows.append({**common, "k": k, **metric, **_precision(output_ids, case),
                            "gate_evidence_retention": retention if method.startswith("complete_pipeline") else None,
                            "answerable_case_retention": (float(bool(retention) and not result.get("abstained")) if retention is not None and method.startswith("complete_pipeline") else retention), "retrieved_ids": ranked[:k], "retained_ids": output_ids})
                except Exception as exc:
                    elapsed = time.perf_counter() - start
                    error = {**base, "outcome": "failed", "failure_type": type(exc).__name__, "elapsed_seconds": elapsed}
                    attempts.append({**error, "stages": []})
                    rows.extend({**error, "k": k} for k in ks)
        memory = memory_summary()
    finally:
        if not tracing:
            tracemalloc.stop()
    aggregates = []
    held_out_available = any(c.get("split") == "held_out" for c in cases)
    for method in methods:
        for k in ks:
            group = [r for r in rows if r["method"] == method and r["k"] == k and (r["split"] == "held_out" if held_out_available else r["split"] == "unspecified")]
            successful = [r for r in group if r["outcome"] == "completed"]
            keys = ("precision", "recall", "mrr", "ndcg", "hit_rate", "candidate_recall", "passage_relevance_precision", "answerable_case_retention", "citation_id_span_validity", "reviewer_coverage")
            metrics = {}
            for key in keys:
                values = [r[key] for r in successful if r.get(key) is not None]
                metrics[key] = statistics.mean(values) if values else None
                metrics[key + "_samples"] = len(values)
            negatives = [r for r in successful if not r["answerable"] and r.get("abstained") is not None]
            aggregates.append({"method": method, "k": k, "questions": len(group), "successful_questions": len(successful),
                "failures": len(group) - len(successful), **metrics,
                "unanswerable_abstention": statistics.mean(r["abstained"] for r in negatives) if negatives else None,
                "unanswerable_abstention_samples": len(negatives), "human_claim_support": None, "contradiction_misses": None})
    stage_values = defaultdict(list)
    for attempt in attempts:
        for stage in attempt["stages"]:
            if stage["seconds"] is not None:
                stage_values[attempt["method"] + ":" + stage["stage"]].append(stage["seconds"])
    report = {"schema_version": 1, "run_id": run_id, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset, "n_questions": len(cases), "k_values": ks, "methods": methods,
        "average_metrics": aggregates, "metric_split": "held_out" if held_out_available else "unspecified_exploratory", "excluded_cases": excluded, "per_query": rows, "attempts": attempts,
        "stage_latency": {key: latency_summary(values) for key, values in stage_values.items()},
        "method_latency": {m: latency_summary([a["elapsed_seconds"] for a in attempts if a["method"] == m]) for m in methods},
        "recovered_model_call_failures": sum(a.get("model_call_failures", 0) for a in attempts),
        "failure_counts": dict(Counter(a.get("failure_type") for a in attempts if a["outcome"] == "failed")),
        "memory": memory, "library_versions": library_versions(),
        "environment": {"logical_cpus": os.cpu_count(), "machine": platform.machine(), "python": platform.python_version(), "platform": platform.platform(), "cross_encoder_device": "cpu", "ollama_gpu_layers_requested": review_state.ollama_gpu_layers(), "ollama_actual_device": "not_verified"},
        "indexed_sources_sha256": {f["source"]: f["sha256"] for f in manifest["files"]},
        "legal_version_label": os.getenv("LEGAL_VERSION", "UNSPECIFIED HISTORICAL TEXT"), "corpus_fingerprint": corpus, "profile_fingerprint": fingerprint(profile),
        "embedding_model": manifest["embedding_model"], "generation_model": os.getenv("OLLAMA_LLM_MODEL", "qwen3:4b"),
        "generation_revision": "unverified_mutable_ollama_tag", "embedding_revision": "unverified_mutable_ollama_tag", "num_ctx": review_state.ollama_num_ctx(),
        "prompt_fingerprints": {"draft": fingerprint(review_state.REVIEW_RULES), "reviewer": fingerprint(review_state.REVIEWER_RULES), "repair": fingerprint(review_state.REPAIR_RULES)},
        "planner_fingerprint": fingerprint(inspect.getsource(plan_queries)),
        "production_retrieval_fingerprint": fingerprint(inspect.getsource(search.retrieve_candidates)),
        "limitations": ["No human grounding metrics until separately adjudicating frozen claims. A local reviewer verdict is not human gold.",
            "Small splits are exploratory, not reliable calibration guarantees.",
            "Dense/BM25/hybrid use one query; multi-query uses up to four with the same 12-per-query/backend and 30-merged caps. Work budgets therefore differ.",
            "Retrieval precision is distinct gold-label credit/k, not exhaustively human-labeled passage precision. Unlabeled passages are not assumed negative.",
            "Recall/MRR/nDCG exclude cases with no positives; failures are counted separately, never as successful abstentions.",
            "Held-out aggregate metrics exclude calibration cases; unspecified legacy splits are exploratory. Ineligible complete-pipeline cases are excluded explicitly, not counted as execution failures.",
            "Experiment order is fixed; caches/model warm-up can affect timing. Latencies exclude no work silently; stage timing excludes checkpoint exports, end-to-end timing includes them.",
            "Default public artifacts contain IDs/hashes/metrics, not source excerpts, query prose or model claim text."]}
    report["fingerprint"] = fingerprint(report)
    atomic_write(output, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    write_evaluation_markdown(report, output.with_suffix(".md"))
    print(f"Evaluation {run_id}: {len(cases)} cases; {len(report['failure_counts'])} failure types; {output}")
    return report


def write_evaluation_markdown(report, path):
    data = report["dataset"]
    lines = ["# Production-path evaluation", "", f"Run: `{report['run_id']}`", "",
        f"Dataset: {data['dataset_type']}; human validated: {data['human_validated']}; cases: {data['sample_size']}; splits: {data['split_counts']}",
        "", "Results are exploratory; no claim of compliance or calibrated legal confidence.", "",
        "| Method | k | Success / cases | Recall | nDCG | MRR | Candidate recall | Unanswerable abstention |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    def number(value): return "not measured" if value is None else f"{value:.4f}"
    for row in report["average_metrics"]:
        lines.append(f"| {row['method']} | {row['k']} | {row['successful_questions']} / {row['questions']} | " +
            " | ".join(number(row[key]) for key in ("recall", "ndcg", "mrr", "candidate_recall", "unanswerable_abstention")) + " |")
    lines += ["", f"Metric split: {report['metric_split']}; excluded cases: {len(report['excluded_cases'])}", "", f"Failures: {report['failure_counts']}", "", "## Latency", "",
              "| Stage | Samples | Median seconds | p95 seconds |", "|---|---:|---:|---:|"]
    for stage, values in report["stage_latency"].items():
        lines.append(f"| {stage} | {values['samples']} | {number(values['median_seconds'])} | {number(values['p95_seconds'])} |")
    lines += ["", f"Memory: {report['memory']}", "", "## Limitations", ""]
    lines += ["- " + limitation for limitation in report["limitations"]]
    atomic_write(path, "\n".join(lines) + "\n")
