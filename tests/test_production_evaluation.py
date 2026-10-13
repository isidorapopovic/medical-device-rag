"""Synthetic Stage 8 metrics/workflows. Never project gold or real performance."""
import copy
import json

import pytest

from mdr_rag import pipeline, search, evaluation, review_state
from mdr_rag.experiments import load_dataset, latency_summary, evaluate_production
from mdr_rag.grounding_evaluation import adjudicate
from mdr_rag.report_state import fingerprint
from mdr_rag.schemas import FindingReview
from mdr_rag.config import ollama_gpu_layers
from test_evidence_gate import gated
from test_report_state import workflow, reviewer


def dataset(path, cases=None, **metadata):
    cases = cases if cases is not None else [{"id": "Q1", "query": "maintenance records", "kind": "device",
        "requirement_id": "R1", "answerable": True, "split": "held_out",
        "relevant": [{"source": "device/records.txt", "chunk_id": "D-2", "page": None}],
        "passage_labels": [{"chunk_id": f"D-{n}", "source": "device/records.txt", "file_sha256": "device-hash", "relevant": n == 2} for n in (1,2,3)],
        "tags": ["qualification", "historical_version", "cross_document"]}]
    value = {"schema_version": 1, "dataset_type": "synthetic", "human_validated": False,
             "reviewer": "deterministic test fixture", "cases": cases, **metadata}
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize("row", [
    {"answerable": True, "relevant": []}, {"relevant": []},
    {"answerable": "false", "relevant": []}, {"answerable": False, "relevant": [{"source": "device/a.txt"}]},
    {"answerable": False}, {"answerable": True, "relevant": [{"source": "legal/a.pdf", "page": 1}]},
])
def test_malformed_positives_are_not_negative_cases(tmp_path, row):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps([{"id": "Q", "query": "q", "kind": "device", **row}]))
    with pytest.raises(ValueError):
        evaluation.load_gold(path)


def test_explicit_unanswerable_has_undefined_positive_metrics(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps([{"id": "Q", "query": "q", "kind": "device", "answerable": False, "relevant": []}]))
    assert evaluation.load_gold(path)[0]["answerable"] is False
    scores = evaluation.rank_scores(["D"], {"D": {"source": "device/a.txt"}}, [], 1)
    assert all(scores[key] is None for key in ("recall", "mrr", "ndcg", "hit_rate"))
    assert scores["precision"] == 0


def test_production_six_method_comparison_redacts_text(gated, tmp_path, monkeypatch):
    path = dataset(tmp_path / "gold.json")
    calls = []
    original = search.retrieve_candidates
    def candidates(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(search, "retrieve_candidates", candidates)
    report = evaluation.evaluate(path, (1, 3), tmp_path / "eval.json", compare_all=True, run_id="synthetic-comparison")
    assert len(report["methods"]) == 6 and len(report["attempts"]) == 6
    assert report["failure_counts"] == {}
    assert all(k["per_backend"] == 12 and k["merged_limit"] == 30 for _, k in calls)
    assert len(calls) == 6  # Includes the production orchestrator's retriever.
    assert all(row["identity"]["backend"] == "cross_encoder" for row in report["per_query"] if row["method"].endswith("cross_encoder"))
    assert "hybrid_reranked" not in report["methods"]
    assert report["dataset"]["dataset_type"] == "synthetic" and not report["dataset"]["human_validated"]
    assert report["dataset"]["split_counts"] == {"held_out": 1}
    assert report["stage_latency"]["complete_pipeline_cross_encoder:validation"]["samples"] == 1
    text = (tmp_path / "eval.json").read_text()
    assert "Other relevant passage" not in text and "Synthetic maintenance records" not in text
    assert "The manufacturer shall" not in text
    assert not (gated[0]["reports"] / "assessment.json").exists()  # No replacement of the user's latest report.
    assert all(row["human_claim_support"] is None for row in report["average_metrics"])


def test_bm25_only_never_calls_embedding_or_reranker(gated, tmp_path, monkeypatch):
    path = dataset(tmp_path / "gold.json")
    monkeypatch.setattr(search, "embeddings", lambda *args: pytest.fail("BM25 embedding call"))
    monkeypatch.setattr(search, "rerank_passages", lambda *args, **kwargs: pytest.fail("Unexpected reranking"))
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["bm25"])
    assert report["methods"] == ["bm25"] and report["failure_counts"] == {}


def test_failure_is_not_abstention_and_exception_excerpts_are_redacted(gated, tmp_path, monkeypatch):
    path = dataset(tmp_path / "gold.json")
    monkeypatch.setattr(search, "retrieve_candidates", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret passage")))
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["dense"])
    assert report["failure_counts"] == {"RuntimeError": 1}
    assert report["average_metrics"][0]["recall"] is None
    assert report["average_metrics"][0]["unanswerable_abstention"] is None
    assert "secret passage" not in json.dumps(report)


def test_strict_none_and_llm_gate_policies_abstain_without_calibration(gated, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_GATE_MODE", "strict")
    monkeypatch.delenv("EVIDENCE_GATE_CALIBRATION", raising=False)
    # LLM score provider is mocked independently; none must not score.
    from mdr_rag import reranking
    original_identity = reranking.reranker_identity
    monkeypatch.setattr(reranking, "reranker_identity", lambda b: {"backend": b, "model": "fake-llm", "score_transformation": "llm_relevance_0_100"} if b == "llm" else {"backend": "none"} if b == "none" else original_identity(b))
    monkeypatch.setattr(review_state, "reranker_identity", reranking.reranker_identity)
    import ollama
    monkeypatch.setattr(ollama, "chat", lambda **kwargs: {"message": {"content": json.dumps({"scores": [
        {"source_id": f"D-{n}", "score": 20} for n in (1,2,3)]})}})
    path = dataset(tmp_path / "gold.json")
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["complete_pipeline_none", "complete_pipeline_llm"], include_reranked=False)
    assert not report["failure_counts"]
    assert all(r["gate_reason"] == "threshold_not_calibrated" and r["abstained"] for r in report["per_query"])
    assert all(not r["strict_gate_passed"] for r in report["per_query"])


def test_reviewer_timeout_is_a_failed_experiment(gated, tmp_path, monkeypatch):
    path = dataset(tmp_path / "gold.json")
    original = pipeline.llm_parse
    def llm(rules, prompt, schema):
        if schema is FindingReview:
            raise TimeoutError("private source")
        return original(rules, prompt, schema)
    monkeypatch.setattr(pipeline, "llm_parse", llm)
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["complete_pipeline_cross_encoder"])
    assert report["average_metrics"][0]["failures"] == 1
    assert report["average_metrics"][0]["unanswerable_abstention"] is None


def test_unanswerable_recall_excluded_and_abstention_measured(gated, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_GATE_MODE", "strict")
    path = dataset(tmp_path / "gold.json", [{"id": "N", "query": "missing evidence", "kind": "device",
        "requirement_id": "R1", "answerable": False, "relevant": [], "split": "held_out"}])
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["complete_pipeline_none"], include_reranked=False)
    metrics = report["average_metrics"][0]
    assert metrics["recall"] is None and metrics["recall_samples"] == 0
    assert metrics["unanswerable_abstention"] == 1 and metrics["unanswerable_abstention_samples"] == 1


def test_incomplete_passage_annotations_do_not_treat_unknown_as_negative(gated, tmp_path):
    path = dataset(tmp_path / "gold.json")
    content = json.loads(path.read_text())
    content["cases"][0]["passage_labels"] = content["cases"][0]["passage_labels"][:1]
    path.write_text(json.dumps(content))
    report = evaluation.evaluate(path, (3,), tmp_path / "eval.json", methods=["dense"], include_reranked=False)
    assert report["per_query"][0]["passage_relevance_precision"] is None
    assert report["per_query"][0]["passage_label_coverage"] == pytest.approx(1/3)


@pytest.mark.parametrize("change", ["human", "split_leak", "source_hash"])
def test_dataset_validation(gated, tmp_path, change):
    path = dataset(tmp_path / "gold.json")
    data = json.loads(path.read_text())
    if change == "human":
        data["human_validated"] = True
    elif change == "split_leak":
        data["cases"].append({**data["cases"][0], "id": "Q2", "split": "calibration"})
    else:
        data["cases"][0]["passage_labels"][0]["file_sha256"] = "changed"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["bm25"])


def test_grounding_adjudication_is_bound_to_frozen_human_labels(gated, tmp_path):
    path = dataset(tmp_path / "gold.json")
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["complete_pipeline_cross_encoder"])
    row = report["per_query"][0]
    label = {key: row[key] for key in ("query_id", "assessment_id", "state_revision", "state_fingerprint", "claim_revision", "context_hash")}
    label["claims"] = [{"claim_id": key, "verdict": "contradicted", "contradiction_missed": True} for key in row["claim_ids"]]
    data = {"schema_version": 1, "dataset_type": "synthetic", "human_validated": False, "reviewer": "mock human",
            "evaluation_fingerprint": report["fingerprint"], "cases": [label]}
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(data))
    result = adjudicate(tmp_path / "eval.json", labels, tmp_path / "grounding.json")
    assert result["claim_support_precision"] == 0 and result["contradiction_misses"] == 1
    data["cases"][0]["context_hash"] = "another source context"
    labels.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="binding"):
        adjudicate(tmp_path / "eval.json", labels, tmp_path / "invalid.json")


def test_duplicate_output_rejected_before_retrieving(gated, tmp_path, monkeypatch):
    path = dataset(tmp_path / "gold.json")
    destination = tmp_path / "eval.json"
    destination.write_text("original")
    monkeypatch.setattr(search, "retrieve_candidates", lambda *a, **k: pytest.fail("No expensive work"))
    with pytest.raises(FileExistsError):
        evaluation.evaluate(path, (1,), destination, methods=["dense"])
    assert destination.read_text() == "original"


@pytest.mark.parametrize("value", ["-1", "word"])
def test_cpu_option_validation(monkeypatch, value):
    monkeypatch.setenv("OLLAMA_NUM_GPU", value)
    with pytest.raises(ValueError): ollama_gpu_layers()


def test_cpu_options_reach_generation_embedding_and_llm_reranker(monkeypatch):
    import ollama
    from mdr_rag.schemas import Answer, RerankBatch
    monkeypatch.setenv("OLLAMA_NUM_GPU", "0")
    seen = []
    def chat(**kwargs):
        seen.append(kwargs["options"])
        payload = {"scores": [{"source_id": "D", "score": 80}]} if "scores" in kwargs["format"]["properties"] else {"answer": "test", "source_ids": [], "limitations": []}
        return {"message": {"content": json.dumps(payload)}}
    monkeypatch.setattr(ollama, "chat", chat)
    def embed(**kwargs):
        seen.append(kwargs["options"])
        return {"embeddings": [[1.0]]}
    monkeypatch.setattr(ollama, "embed", embed)
    pipeline.llm_parse("data", "data", Answer)
    search.embeddings(["data"])
    search.rerank_passages("data", [{"id": "D", "text": "source data", "meta": {}}], backend="llm")
    assert all(options["num_gpu"] == 0 for options in seen)
    assert latency_summary([1,2,3,4])["p95_seconds"] == 4


def test_heldout_aggregates_do_not_include_calibration_cases(gated, tmp_path):
    path = dataset(tmp_path / "gold.json")
    data = json.loads(path.read_text())
    data["cases"].append({"id": "TRAIN", "query": "a different calibration question", "kind": "device",
        "requirement_id": "R2", "split": "calibration", "answerable": False, "relevant": []})
    path.write_text(json.dumps(data))
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["dense", "complete_pipeline_cross_encoder"])
    assert report["metric_split"] == "held_out"
    assert all(r["questions"] == 1 for r in report["average_metrics"])
    assert report["excluded_cases"] == [{"query_id": "TRAIN", "method": "complete_pipeline_cross_encoder", "reason": "requires_held_out_device_requirement"}]
    assert report["failure_counts"] == {}


def test_same_requirement_cannot_leak_across_splits(tmp_path):
    path = dataset(tmp_path / "gold.json")
    data = json.loads(path.read_text())
    data["cases"].append({**data["cases"][0], "id": "other", "query": "paraphrase differs", "split": "calibration"})
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="requirement"):
        load_dataset(path)


def test_gate_retention_is_not_published_answer_retention(gated, tmp_path, monkeypatch):
    path = dataset(tmp_path / "gold.json")
    original = pipeline.llm_parse
    def models(rules, prompt, schema):
        result = original(rules, prompt, schema)
        if schema is FindingReview:
            result.claims[0].verdict = "insufficient"
        return result
    monkeypatch.setattr(pipeline, "llm_parse", models)
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["complete_pipeline_cross_encoder"])
    row = report["per_query"][0]
    assert row["gate_evidence_retention"] == 1 and row["answerable_case_retention"] == 0
    assert row["audit_status"] == "validation_failed" and row["reviewer_inventory_valid"]
    assert row["citation_id_span_validity"] == 1  # Genuine raw quote, semantic rejection.
    assert row["published_citation_id_span_validity"] is None


def test_model_chosen_claim_id_cannot_leak_prose(gated, tmp_path, monkeypatch):
    path = dataset(tmp_path / "gold.json")
    original = pipeline.llm_parse
    def models(rules, prompt, schema):
        result = original(rules, prompt, schema)
        if schema is not FindingReview:
            result.claims[0].claim_id = "private source prose chosen as an ID"
        return result
    monkeypatch.setattr(pipeline, "llm_parse", models)
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["complete_pipeline_cross_encoder"])
    assert report["per_query"][0]["claim_ids"][0].startswith("CL-")
    assert "private source prose chosen as an ID" not in (tmp_path / "eval.json").read_text()


def test_unanswerable_can_still_have_partially_relevant_passages(gated, tmp_path):
    path = dataset(tmp_path / "gold.json")
    data = json.loads(path.read_text())
    data["cases"][0].update(answerable=False, relevant=[])
    path.write_text(json.dumps(data))
    report = evaluation.evaluate(path, (1,), tmp_path / "eval.json", methods=["multi_query_cross_encoder"])
    row = report["per_query"][0]
    assert row["recall"] is None and row["passage_relevance_precision"] == 1
    assert row["abstained"] is None  # Retrieval alone cannot establish answerability.
