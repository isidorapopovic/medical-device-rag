import copy
import json
from types import SimpleNamespace

import pytest

from mdr_rag import pipeline, review_state, search, reranking, report_state
from mdr_rag.evidence_gate import Calibration, GateContext, fingerprint, screen, settings, gate_context
from mdr_rag.gate_evaluation import tune, metrics, calibrate_labels, evaluate_labels, load_labeled_runs
from mdr_rag.schemas import Finding, ObligationCoverage, FindingReview
from test_report_state import workflow, reviewer
from test_reranking import FakeScorer, identity


def cases():
    result = []
    for key, split, answerable, scores in (("C1", "calibration", True, [(8, True), (2, False)]),
                                          ("C2", "calibration", False, [(3, False)]),
                                          ("H1", "held_out", True, [(7, True), (4, False)]),
                                          ("H2", "held_out", False, [(1, False)])):
        result.append({"id": key, "split": split, "answerable": answerable, "query_fingerprint": fingerprint(key),
                      "passages": [{"id": f"D-{n}", "score": score, "relevant": relevant,
                                    "label_kind": "positive" if relevant else "hard_negative"} for n, (score, relevant) in enumerate(scores)]})
    return result


def context():
    return GateContext(reranker_identity=identity(), retrieval_configuration={"mode": "hybrid"},
                       corpus_fingerprint="corpus", profile_fingerprint="profile")


def calibration(ctx=None, rows=None):
    rows = rows or cases()
    return tune(ctx or context(), rows, "Synthetic test fixture (not production human labels)", fingerprint(rows))


@pytest.fixture
def gated(workflow, monkeypatch):
    monkeypatch.setenv("EVIDENCE_GATE_MODE", "experimental")
    monkeypatch.setenv("EVIDENCE_GATE_THRESHOLD", "1.5")
    monkeypatch.setenv("RERANK_BACKEND", "cross_encoder")
    monkeypatch.setenv("RETRIEVAL_MODE", "dense")
    records = [{"id": f"D-{n}", "text": "Synthetic maintenance records" if n == 1 else "Other relevant passage unrelated qualifier" if n == 2 else "Irrelevant passage not addressing this obligation",
                "meta": {"kind": "device", "source": "device/records.txt", "sha256": "device-hash", "page": 0, "block": n}}
               for n in (1, 2, 3)]
    class Collection:
        def get(self, **kwargs):
            return {"ids": [p["id"] for p in records], "documents": [p["text"] for p in records], "metadatas": [p["meta"] for p in records]}
        def query(self, **kwargs):
            return {"ids": [[p["id"] for p in records]]}
    monkeypatch.setattr(search, "collection", Collection)
    monkeypatch.setattr(search, "embeddings", lambda *args: [[1.0]])
    monkeypatch.setattr(reranking, "reranker_identity", lambda backend: identity())
    monkeypatch.setattr(review_state, "reranker_identity", lambda backend: identity())
    scorer = FakeScorer()
    monkeypatch.setattr(reranking, "get_scorer", lambda info: scorer)
    original_llm = workflow["llm"]
    prompts = []
    def draft(rules, prompt, schema):
        if schema is FindingReview:
            return reviewer(prompt)
        prompts.append(prompt)
        finding = original_llm(rules, prompt, schema)
        finding.claims[0].evidence[0].source_id = "D-2"
        finding.claims[0].evidence[0].exact_quote = "Other relevant passage"
        finding.obligation_coverage = [ObligationCoverage(obligation_id="R1", status="supported", evidence_ids=["D-2"], explanation="Synthetic coverage")]
        return finding
    monkeypatch.setattr(pipeline, "llm_parse", draft)
    return workflow, records, scorer, prompts


def test_all_rejected_skips_drafting_and_no_topk_fallback(gated, monkeypatch):
    workflow, _, scorer, prompts = gated
    monkeypatch.setenv("EVIDENCE_GATE_THRESHOLD", "9")
    state = pipeline.run_review(assessment_id="demo", limit=1)
    section = state.sections["R1"]
    assert section.finding.status == "insufficient_evidence"
    assert section.audit_status == "gate_abstained"
    assert section.evidence_gate.accepted_ids == section.evidence_gate.draft_ids == []
    assert len(section.evidence_gate.rejected_ids) == 3
    assert prompts == workflow["calls"]["llm"] == []
    assert not any(c.stage == "review_draft" for c in section.model_calls)
    assert section.draft_call_id is None
    assert len(scorer.calls) == 1


def test_only_accepted_subset_enters_draft_and_gate_before_topk(gated):
    workflow, _, _, prompts = gated
    state = pipeline.run_review(assessment_id="demo", limit=1, k=1)
    section = state.sections["R1"]
    assert len(section.passages) == 3
    assert section.evidence_gate.accepted_ids == section.evidence_gate.draft_ids == ["D-2"]
    device_text = prompts[0].split("RETRIEVED DEVICE EXCERPTS:")[1]
    assert "SOURCE_ID: D-2" in device_text and "SOURCE_ID: D-1" not in device_text and "SOURCE_ID: D-3" not in device_text
    assert section.finding.status == "supported"
    assert section.evidence_gate.strict_validation_passed is False
    assert section.finding_history[-1]["evidence_gate"]["rejected_ids"]
    report = report_state.compatibility_report(state)
    assert report["findings"][0]["evidence_gate"]["mode"] == "experimental"
    assert "No successful strict gate validation" in (workflow["store"].directory / "assessment.md").read_text()


def test_default_strict_uncalibrated_abstains(gated, monkeypatch):
    monkeypatch.delenv("EVIDENCE_GATE_MODE")
    state = pipeline.run_review(assessment_id="demo", limit=1)
    assert state.sections["R1"].evidence_gate.reason == "threshold_not_calibrated"
    assert state.sections["R1"].finding.status == "insufficient_evidence"
    assert gated[3] == []


def test_calibrated_strict_pass_and_context_mismatch(gated, monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_GATE_MODE", "strict")
    cfg = review_state.configuration(7)
    ctx = gate_context(cfg, review_state.corpus_hash(gated[0]["manifest"]), gated[0]["profile"])
    rows = cases()
    # Fixture's good passage has score 2; select 2 from calibration labels only.
    rows[0]["passages"][0]["score"] = 2
    rows[0]["passages"][1]["score"] = 0
    rows[1]["passages"][0]["score"] = 1
    artifact = calibration(ctx, rows)
    path = tmp_path / "calibration.json"
    path.write_text(artifact.model_dump_json())
    monkeypatch.setenv("EVIDENCE_GATE_CALIBRATION", str(path))
    before = pipeline.run_review(assessment_id="demo", limit=1)
    assert before.sections["R1"].evidence_gate.strict_validation_passed
    assert before.sections["R1"].evidence_gate.calibration_fingerprint == artifact.fingerprint
    calls = len(gated[2].calls)
    # A valid calibration for another corpus must block strict reuse, preserving retrieval.
    other = calibration(ctx.model_copy(update={"corpus_fingerprint": "other-corpus"}), rows)
    path.write_text(other.model_dump_json())
    after = pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert after.sections["R1"].evidence_gate.reason == "calibration_mismatch"
    assert after.sections["R1"].finding.status == "insufficient_evidence"
    assert len(gated[2].calls) == calls
    assert len(gated[3]) == 1


def test_disabled_gate_is_visible_and_not_strict(workflow):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    gate = state.sections["R1"].evidence_gate
    assert gate.mode == gate.status == "disabled" and not gate.strict_validation_passed
    assert "gate_disabled" in gate.reason


def test_backend_failure_is_execution_error_not_insufficiency(gated):
    gated[2].scores = []
    with pytest.raises(ValueError, match="one-to-one"):
        pipeline.run_review(assessment_id="demo", limit=1)
    section = gated[0]["store"].load().sections["R1"]
    assert section.execution_status == "failed" and section.finding is None and section.evidence_gate is None


def test_empty_indexed_corpus_is_error(gated):
    gated[1].clear()
    with pytest.raises(RuntimeError, match="corpus is empty"):
        pipeline.run_review(assessment_id="demo", limit=1)
    section = gated[0]["store"].load().sections["R1"]
    assert section.finding is None and section.execution_status == "failed"


def test_missing_index_manifest_is_not_evidence_absence(gated, monkeypatch):
    def missing():
        raise FileNotFoundError("manifest missing")
    monkeypatch.setattr(pipeline, "check_manifest", missing)
    with pytest.raises(RuntimeError, match="alignment failed"):
        pipeline.run_review(assessment_id="demo", limit=1)
    assert not gated[0]["store"].path.exists()


def test_no_retrieved_matches_in_nonempty_corpus_abstains(gated, monkeypatch):
    monkeypatch.setenv("EVIDENCE_GATE_MODE", "strict")
    class Collection:
        def get(self, **kwargs):
            return {"ids": ["D-1"], "documents": ["Unrelated indexed content"], "metadatas": [gated[1][0]["meta"]]}
        def query(self, **kwargs):
            return {"ids": [[]]}
    monkeypatch.setattr(search, "collection", Collection)
    state = pipeline.run_review(assessment_id="demo", limit=1)
    assert state.sections["R1"].execution_status == "completed"
    assert state.sections["R1"].finding.status == "insufficient_evidence"


def test_passing_scores_do_not_cover_missing_qualifiers(gated):
    gated[0]["draft"]["requirements"][0]["qualifiers"] = ["specified explicit qualifier"]
    gated[0]["draft_path"].write_text(json.dumps(gated[0]["draft"]))
    state = pipeline.run_review(assessment_id="demo", limit=1)
    assert state.sections["R1"].finding.status == "needs_review"
    assert "status_overstates_atomic_coverage" in state.sections["R1"].citation_issues


def test_missing_atomic_coverage_needs_review(gated, monkeypatch):
    original = pipeline.llm_parse
    def missing(*args):
        finding = original(*args)
        finding.obligation_coverage = []
        return finding
    monkeypatch.setattr(pipeline, "llm_parse", missing)
    state = pipeline.run_review(assessment_id="demo", limit=1)
    assert state.sections["R1"].finding.status == "needs_review"


def test_threshold_tuning_never_uses_held_out_scores():
    first = calibration()
    changed = cases()
    changed[2]["passages"][0]["score"] = 1000
    changed[3]["passages"][0]["score"] = 999
    second = calibration(rows=changed)
    assert first.selected_threshold == second.selected_threshold == 8
    assert first.calibration_metrics == second.calibration_metrics
    assert first.validation_metrics != second.validation_metrics
    assert first.validation_metrics["answerable_hit_rate"] == 0


@pytest.mark.parametrize("field,value", [("corpus_fingerprint", "changed"), ("profile_fingerprint", "changed"),
                                        ("retrieval_configuration", {"mode": "bm25"})])
def test_context_identity_mismatches_block_strict(field, value):
    artifact = calibration()
    cfg = {"gate_mode": "strict", "gate_threshold": None, "gate_calibration": artifact.model_dump(), "k": 7}
    passage = SimpleNamespace(id="D-1")
    result = screen([passage], None, cfg, context().model_copy(update={field: value}), [])
    assert result.reason == "calibration_mismatch" and not result.accepted_ids


@pytest.mark.parametrize("identity_change", [{"backend": "llm"}, {"revision": "another-revision"},
                                            {"score_transformation": "sigmoid"}, {"libraries": {"torch": "changed"}}])
def test_scorer_identity_mismatch_not_reused(identity_change):
    ctx = context().model_copy(update={"reranker_identity": {**identity(), **identity_change}})
    artifact = calibration()
    result = screen([SimpleNamespace(id="D-1")], None,
                    {"gate_mode": "strict", "gate_threshold": None, "gate_calibration": artifact.model_dump(), "k": 7}, ctx, [])
    assert result.reason == "calibration_mismatch"


def test_calibration_fingerprint_tampering_rejected():
    artifact = calibration().model_dump()
    artifact["selected_threshold"] = 0
    with pytest.raises(ValueError, match="fingerprint"):
        Calibration.model_validate(artifact)


@pytest.mark.parametrize("mode,threshold", [("experimental", ""), ("experimental", "nan"), ("experimental", "inf"), ("bad", "1")])
def test_gate_configuration_validation(monkeypatch, mode, threshold):
    monkeypatch.setenv("EVIDENCE_GATE_MODE", mode)
    monkeypatch.setenv("EVIDENCE_GATE_THRESHOLD", threshold)
    with pytest.raises(ValueError):
        settings()


def test_rrf_scores_cannot_be_thresholded():
    with pytest.raises(RuntimeError, match="RRF"):
        screen([SimpleNamespace(id="D-1")], {"candidates": [{"id": "D-1", "fusion_score": 99}]},
               {"gate_mode": "experimental", "gate_threshold": 1, "gate_calibration": None, "k": 7}, context(), [])


def test_split_leakage_and_missing_hard_negatives_rejected():
    rows = cases()
    rows[2]["query_fingerprint"] = rows[0]["query_fingerprint"]
    with pytest.raises(ValueError, match="distinct"):
        calibration(rows=rows)
    rows = cases()
    for row in rows:
        for passage in row["passages"]:
            if not passage["relevant"]:
                passage["label_kind"] = "negative"
    with pytest.raises(ValueError, match="hard negatives"):
        calibration(rows=rows)


def saved_labels(gated, tmp_path):
    from test_report_state import requirement
    data = gated[0]
    data["draft"]["requirements"].append(requirement("R4"))
    data["draft_path"].write_text(json.dumps(data["draft"]))
    # Strict without a calibration collects scores but calls no drafting model.
    import os
    os.environ["EVIDENCE_GATE_MODE"] = "strict"
    state = pipeline.run_review(assessment_id="demo")
    rows = []
    for n, key in enumerate(state.sections):
        answerable = n % 2 == 0
        rows.append({"id": key, "assessment": str(data["store"].path), "requirement_id": key,
                     "split": "calibration" if n < 2 else "held_out", "answerable": answerable,
                     "passages": [{"id": f"D-{p}", "relevant": answerable and p == 2,
                                   "label_kind": "positive" if answerable and p == 2 else "hard_negative"} for p in (1, 2, 3)]})
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"human_validated": True, "reviewer": "Synthetic test fixture, not real calibration", "cases": rows}))
    return path


def test_calibration_and_heldout_evaluation_from_frozen_scores(gated, tmp_path):
    path = saved_labels(gated, tmp_path)
    destination = tmp_path / "calibration.json"
    artifact = calibrate_labels(path, destination)
    assert artifact.context.reranker_identity == identity()
    assert artifact.validation_metrics["unanswerable_questions"] == 1
    context_value, rows, _, label_hash = load_labeled_runs(path)
    assert {p["score"] for c in rows for p in c["passages"]} == {1.0, 2.0}
    assert all(p["buffer_id"] for c in rows for p in c["passages"])
    assert artifact.labels_fingerprint == label_hash
    evaluated = evaluate_labels(path, destination, tmp_path / "heldout.json")
    assert evaluated["metrics"]["questions"] == 2
    assert evaluated["calibration_fingerprint"] == artifact.fingerprint
    original = destination.read_bytes()
    with pytest.raises(FileExistsError, match="distinct filename"):
        calibrate_labels(path, destination)
    assert destination.read_bytes() == original


def test_incomplete_or_unreviewed_labels_never_calibrate(gated, tmp_path):
    path = saved_labels(gated, tmp_path)
    data = json.loads(path.read_text())
    data["human_validated"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="human_validated"):
        load_labeled_runs(path)
    data["human_validated"] = True
    data["cases"][0]["passages"].pop()
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="every scored candidate"):
        load_labeled_runs(path)


def test_manual_label_scores_are_rejected(gated, tmp_path):
    path = saved_labels(gated, tmp_path)
    data = json.loads(path.read_text())
    data["cases"][0]["passages"][0]["score"] = 999
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hand-entered"):
        load_labeled_runs(path)


def test_gate_checkpoint_resumes_without_retrieval(gated, monkeypatch):
    original = pipeline.llm_parse
    def interrupt(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(pipeline, "llm_parse", interrupt)
    with pytest.raises(KeyboardInterrupt):
        pipeline.run_review(assessment_id="demo", limit=1)
    section = gated[0]["store"].load().sections["R1"]
    assert section.checkpoint == "gate" and section.evidence_gate.draft_ids == ["D-2"]
    before = len(gated[2].calls)
    monkeypatch.setattr(pipeline, "llm_parse", original)
    pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert len(gated[2].calls) == before


def test_cli_calibration_and_gate_evaluation(monkeypatch):
    import main
    import mdr_rag.gate_evaluation as gate_eval
    received = []
    monkeypatch.setattr(gate_eval, "calibrate_labels", lambda *args: received.append(args))
    monkeypatch.setattr("sys.argv", ["main.py", "calibrate-gate", "--labels", "labels.json", "--out", "cal.json"])
    assert main.main() == 0 and received == [("labels.json", "cal.json")]
    monkeypatch.setattr(gate_eval, "evaluate_labels", lambda *args: received.append(args))
    monkeypatch.setattr("sys.argv", ["main.py", "evaluate", "--gate-labels", "labels.json", "--gate-calibration", "cal.json", "--out", "eval.json"])
    assert main.main() == 0 and received[-1] == ("labels.json", "cal.json", "eval.json")


def test_targeted_gate_updates_preserve_unaffected_sections(gated):
    before = pipeline.run_review(assessment_id="demo")
    after = pipeline.run_review(assessment_id="demo", requirement_id="R2", refresh=True)
    for key in ("R1", "R3"):
        assert after.sections[key].model_dump() == before.sections[key].model_dump()
    assert after.sections["R2"].revision == before.sections["R2"].revision + 1


def test_malformed_calibration_never_overwrites_report(gated, monkeypatch, tmp_path):
    pipeline.run_review(assessment_id="demo", limit=1)
    original = gated[0]["store"].path.read_bytes()
    path = tmp_path / "malformed.json"
    path.write_text('{broken')
    monkeypatch.setenv("EVIDENCE_GATE_MODE", "strict")
    monkeypatch.setenv("EVIDENCE_GATE_CALIBRATION", str(path))
    with pytest.raises(RuntimeError, match="Malformed calibration"):
        pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert gated[0]["store"].path.read_bytes() == original


def test_rejected_passage_cannot_enter_atomic_coverage(gated, monkeypatch):
    original = pipeline.llm_parse
    def wrong(*args):
        finding = original(*args)
        finding.obligation_coverage[0].evidence_ids = ["D-3"]
        return finding
    monkeypatch.setattr(pipeline, "llm_parse", wrong)
    assert pipeline.run_review(assessment_id="demo", limit=1).sections["R1"].finding.status == "needs_review"


def test_multiple_explicit_atomic_obligations_require_all_coverage(gated):
    data = gated[0]
    data["draft"]["requirements"][0]["atomic_obligations"] = [
        {"obligation_id": "R1", "text": "Original explicit atomic obligation", "qualifiers": []},
        {"obligation_id": "R1-O2", "text": "Second explicitly registered obligation", "qualifiers": []}]
    data["draft_path"].write_text(json.dumps(data["draft"]))
    section = pipeline.run_review(assessment_id="demo", limit=1).sections["R1"]
    assert len(section.evidence_gate.obligations) == 2
    assert section.finding.status == "needs_review"


def test_changed_profile_blocks_calibration_reuse_and_reruns_retrieval(gated, monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_GATE_MODE", "strict")
    cfg = review_state.configuration(7)
    ctx = gate_context(cfg, review_state.corpus_hash(gated[0]["manifest"]), gated[0]["profile"])
    path = tmp_path / "cal.json"
    path.write_text(calibration(ctx).model_dump_json())
    monkeypatch.setenv("EVIDENCE_GATE_CALIBRATION", str(path))
    pipeline.run_review(assessment_id="demo", limit=1)
    before = len(gated[2].calls)
    gated[0]["profile"]["intended_purpose"] = "Changed explicit profile fact"
    section = pipeline.run_review(assessment_id="demo", resume=True, limit=1).sections["R1"]
    assert section.evidence_gate.reason == "calibration_mismatch"
    assert len(gated[2].calls) == before + 1


def test_transient_windows_replace_retries_atomically(tmp_path, monkeypatch):
    if report_state.os.name != "nt":
        pytest.skip("Windows-specific sharing-lock handling")
    path = tmp_path / "state.json"
    path.write_text("previous")
    original = report_state.os.replace
    attempts = []
    def transient(source, destination):
        attempts.append((source, destination))
        if len(attempts) == 1:
            raise PermissionError("temporary reader lock")
        original(source, destination)
    monkeypatch.setattr(report_state.os, "replace", transient)
    monkeypatch.setattr(report_state.time, "sleep", lambda *args: None)
    report_state.atomic_write(path, "next")
    assert len(attempts) == 2 and path.read_text() == "next"
    assert attempts[0] == attempts[1]


def test_persistent_replace_denial_preserves_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("previous")
    attempts = []
    def denied(*args):
        attempts.append(args)
        raise PermissionError("persistent denial")
    monkeypatch.setattr(report_state.os, "replace", denied)
    monkeypatch.setattr(report_state.time, "sleep", lambda *args: None)
    with pytest.raises(PermissionError):
        report_state.atomic_write(path, "next")
    assert len(attempts) == (5 if report_state.os.name == "nt" else 1)
    assert path.read_text() == "previous"
    assert not list(tmp_path.glob("*.tmp"))


def test_disabled_gate_with_no_passages_also_skips_drafting(workflow, monkeypatch):
    monkeypatch.setattr(pipeline, "hybrid_search", lambda *args, **kwargs: [])
    section = pipeline.run_review(assessment_id="demo", limit=1).sections["R1"]
    assert section.evidence_gate.mode == "disabled"
    assert section.finding.status == "insufficient_evidence"
    assert workflow["calls"]["llm"] == []
