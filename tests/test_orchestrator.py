"""Six-role synthetic CLI workflows. No live API, model download or user files."""
import copy
import json
import os
import sys

import pytest

from mdr_rag import pipeline, review_state, report_state
from mdr_rag.roles import (AssessmentOrchestrator, RequirementAnalyst, VersionedRegister,
                           RetrievalResult, ReviewedFinding, AuditResult, ReportExport)
from mdr_rag.schemas import RequirementBatch, RequirementCandidate, FindingReview
from mdr_rag.graph_viz import build_evidence_graph, draw_graph
from test_report_state import workflow, reviewer
from test_evidence_gate import gated


def cli(monkeypatch, args):
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    return main.main()


def test_complete_six_role_cli_workflow_without_apis(gated, monkeypatch, tmp_path):
    workflow, records, scorer, prompts = gated
    import main
    import ollama
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: pytest.fail("Live Ollama forbidden"))
    monkeypatch.setenv("LEGAL_VERSION", "Synthetic historical legal text")
    class PDF:
        def __len__(self): return 1
        def close(self): pass
    monkeypatch.setattr(pipeline.fitz, "open", lambda *args: PDF())
    monkeypatch.setattr(main, "extract_requirements", workflow["extract"])
    original = pipeline.llm_parse
    def models(rules, prompt, schema):
        if schema is RequirementBatch:
            return RequirementBatch(items=[RequirementCandidate(**{key: row[key] for key in
                ("requirement", "exact_quote", "provision", "applies_to")}) for row in workflow["draft"]["requirements"]])
        # Gated fixture's coverage is tied to R1; this run uses extracted IDs.
        if schema is FindingReview:
            return reviewer(prompt)
        finding = original(rules, prompt, schema)
        key = json.loads(prompt.split("ATOMIC OBLIGATIONS:\n")[1].split("\n\nRETRIEVED")[0])[0]["obligation_id"]
        finding.obligation_coverage[0].obligation_id = key
        finding.claims[0].obligation_ids = [key]
        return finding
    monkeypatch.setattr(pipeline, "llm_parse", models)
    assert cli(monkeypatch, ["extract", "--pages", "1", "--legal-file", "law.pdf"]) == 0
    register = json.loads(workflow["draft_path"].read_text())
    assert VersionedRegister.model_validate(register).register_fingerprint
    assert len(list((workflow["root"] / "requirements" / "revisions").glob("*.json"))) == 2
    workflow["profile"]["actor_role"] = "distributor"  # Always explicitly unverified.
    assert cli(monkeypatch, ["--retrieval", "hybrid", "--reranker", "cross_encoder",
        "review", "--limit", "2", "--assessment-id", "demo"]) == 0
    partial = workflow["store"].load()
    ids = list(partial.sections)
    assert partial.partial_run and partial.execution_counts == {"completed": 2, "pending": 1}
    assert all(s.applicability_result.status == "possibly_not_applicable" for s in list(partial.sections.values())[:2])
    assert all(s.finding.status == "supported" for s in list(partial.sections.values())[:2])
    assert all(s.applicability_result.retrieval_policy == "search_device_evidence" for s in list(partial.sections.values())[:2])
    assert len(scorer.calls) == 2
    report = report_state.compatibility_report(partial)
    graph, stats = build_evidence_graph(report)
    assert stats["total_requirements_in_graph"] == 3 and stats["assessed_requirements_in_graph"] == 2
    assert stats["unassessed_requirements_in_graph"] == 1 and stats["requirements_without_cited_evidence"] == 0
    assert stats["relation_counts"]["AUDITED_SUPPORT"] == 2
    assert stats["relation_counts"]["RETRIEVED"] == 6
    # Continuation uses saved settings, despite hostile ambient changes.
    monkeypatch.setenv("OLLAMA_LLM_MODEL", "unselected-model")
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    monkeypatch.setenv("EVIDENCE_GATE_MODE", "strict")
    assert cli(monkeypatch, ["review", "--assessment-id", "demo", "--resume"]) == 0
    complete = workflow["store"].load()
    assert not complete.partial_run and complete.execution_counts == {"completed": 3}
    assert complete.config["llm_model"] == "qwen3:4b" and complete.config["retrieval_mode"] == "hybrid"
    others = {key: copy.deepcopy(complete.sections[key].model_dump()) for key in (ids[0], ids[2])}
    register["requirements"][1]["requirement"] = "Updated existing atomic obligation paraphrase"
    register["requirements"][1]["requirement_revision"] += 1
    register["register_fingerprint"] = ""
    workflow["draft_path"].write_text(RequirementAnalyst().register(register).model_dump_json())
    assert cli(monkeypatch, ["review", "--assessment-id", "demo", "--requirement-id", ids[1], "--refresh"]) == 0
    final = workflow["store"].load()
    assert {key: final.sections[key].model_dump() for key in others} == others
    assert final.sections[ids[1]].revision == 2 and len(scorer.calls) == 4
    monkeypatch.setattr(pipeline, "llm_parse", lambda *a: pytest.fail("Rendering cannot infer"))
    assert cli(monkeypatch, ["report", "--assessment-id", "demo"]) == 0
    report = json.loads((workflow["store"].directory / "exports" / "assessment.json").read_text())
    graph, stats = build_evidence_graph(report)
    assert stats["gate_modes"] == {"experimental": 3} and stats["strict_gate_passed_requirements"] == 0
    assert stats["audit_counts"] == {"semantic_checked": 3}
    assert stats["applicability_counts"] == {"possibly_not_applicable": 3}
    result = draw_graph(graph, stats, tmp_path / "six_roles.html")
    assert result["visualization_shows"] == 3
    markdown = (workflow["store"].directory / "exports" / "assessment.md").read_text()
    assert "Missing applicability facts" in markdown and "Published structured claims" in markdown
    assert "experimental" in markdown and "No successful strict gate validation" in markdown


def test_typed_role_outputs_and_writer_add_no_finding(workflow):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    role = AssessmentOrchestrator()
    section = state.sections["R1"]
    from mdr_rag.source_buffer import SourceBuffer
    assert isinstance(role.evidence_retriever.result(section, SourceBuffer(state.source_buffer)), RetrievalResult)
    reviewed = role.evidence_reviewer.result(section)
    assert isinstance(reviewed, ReviewedFinding) and isinstance(reviewed.audit, AuditResult)
    assert reviewed.audit.performed and reviewed.audit.passed
    original = state.model_dump()
    exported = role.report_writer.write(state, workflow["reports"] / "typed")
    assert isinstance(exported, ReportExport) and exported.partial_run and exported.assessed_requirements == 1
    assert state.model_dump() == original


def test_gate_short_circuit_still_records_applicability(gated, monkeypatch):
    monkeypatch.setenv("EVIDENCE_GATE_THRESHOLD", "9")
    state = pipeline.run_review(assessment_id="demo", limit=1)
    section = state.sections["R1"]
    assert section.applicability_result.status == "uncertain"
    assert section.finding.status == "insufficient_evidence"
    assert not any(c.stage.startswith("review_") for c in section.model_calls)
    graph, stats = build_evidence_graph(report_state.compatibility_report(state))
    assert graph.nodes["requirement:R1"]["status"] == "insufficient_evidence"
    assert stats["execution_counts"] == {"completed": 1, "pending": 2}
    assert not stats["relation_counts"].get("AUDITED_SUPPORT")


def test_saved_configuration_and_explicit_override_are_scoped(workflow, monkeypatch):
    before = pipeline.run_review(assessment_id="demo")
    monkeypatch.setenv("OLLAMA_LLM_MODEL", "different")
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    after = pipeline.run_review(assessment_id="demo", resume=True)
    assert after.config["llm_model"] == before.config["llm_model"]
    assert after.config["retrieval_mode"] == before.config["retrieval_mode"]
    assert len(workflow["calls"]["llm"]) == 3
    assert os.environ["OLLAMA_LLM_MODEL"] == "different"
    changed = pipeline.run_review(assessment_id="demo", requirement_id="R2", config_overrides={"llm_model": "explicit"})
    assert changed.config["llm_model"] == "explicit" and changed.sections["R1"].execution_status == "stale"
    assert len(workflow["calls"]["llm"]) == 4 and len(workflow["calls"]["retrieval"]) == 3


@pytest.mark.parametrize("args", [
    ["review", "--limit", "0"], ["review", "--k", "0"],
    ["review", "--resume"], ["review", "--refresh"],
    ["review", "--assessment-id", "demo", "--requirement-id", "unknown"],
    ["review", "--assessment-id", "demo", "--resume", "--requirement-id", "R1"],
    ["review", "--assessment-id", "demo", "--limit", "2", "--requirement-id", "R1"],
])
def test_cli_invalid_operations_fail_without_model_calls(workflow, monkeypatch, args):
    assert cli(monkeypatch, args) == 1
    assert workflow["calls"]["llm"] == []


def test_legacy_exports_and_graph_never_promote_audit(workflow, tmp_path):
    current = pipeline.run_review(assessment_id="demo", limit=1)
    legacy = report_state.compatibility_report(current)
    for key in ("source_buffer", "model_calls", "sections"):
        legacy.pop(key)
    legacy["findings"][0].pop("claim_links")
    legacy["findings"][0].pop("semantic_validation")
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy))
    imported = report_state.import_legacy(path, workflow["root"], "legacy")
    output = report_state.compatibility_report(imported, historical=True)
    assert output["findings"][0]["audit_status"] == "legacy_unverified"
    assert output["findings"][0]["applicability"]["status"] == "uncertain"
    graph, stats = build_evidence_graph(output)
    assert stats["requirements_with_cited_evidence"] == 1
    assert not stats["relation_counts"].get("AUDITED_SUPPORT")
    assert not stats["human_validated"] and output["limitations"]


def test_unsourced_scope_label_is_not_a_legal_condition(workflow):
    workflow["draft"]["requirements"][0]["applies_to"] = "implanted class III device"
    workflow["draft_path"].write_text(json.dumps(workflow["draft"]))
    result = pipeline.run_review(assessment_id="demo", limit=1).sections["R1"].applicability_result
    assert result.status == "uncertain" and result.legal_conditions == []
    assert all(not fact.verified for fact in result.profile_facts)
    assert any("raw legal citation" in fact for fact in result.missing_facts)


def test_cli_interruption_resumes_without_unaffected_calls(workflow, monkeypatch):
    original = workflow["llm"]
    def interrupt(rules, prompt, schema):
        if schema is FindingReview:
            raise KeyboardInterrupt()
        return original(rules, prompt, schema)
    monkeypatch.setattr(pipeline, "llm_parse", interrupt)
    with pytest.raises(KeyboardInterrupt):
        cli(monkeypatch, ["review", "--assessment-id", "demo", "--limit", "1"])
    saved = workflow["store"].load()
    assert saved.sections["R1"].checkpoint == "draft"
    assert saved.sections["R1"].applicability_result is not None
    monkeypatch.setattr(pipeline, "llm_parse", original)
    assert cli(monkeypatch, ["review", "--assessment-id", "demo", "--resume", "--limit", "1"]) == 0
    final = workflow["store"].load()
    assert final.sections["R1"].audit_status == "semantic_checked"
    assert final.execution_counts == {"completed": 1, "pending": 2}
    assert len(workflow["calls"]["llm"]) == len(workflow["calls"]["retrieval"]) == 1


def test_invalid_draft_schema_is_failed_execution_in_graph(workflow, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "llm_parse", lambda *args: {"status": "supported", "made_up": "fact"})
    assert cli(monkeypatch, ["review", "--assessment-id", "demo", "--limit", "1"]) == 1
    state = workflow["store"].load()
    graph, stats = build_evidence_graph(report_state.compatibility_report(state))
    assert state.sections["R1"].finding is None
    assert graph.nodes["requirement:R1"]["status"] == "failed"
    assert stats["assessed_requirements_in_graph"] == 0
    assert stats["requirements_without_cited_evidence"] == 0
    assert stats["execution_counts"] == {"failed": 1, "pending": 2}
    draw_graph(graph, stats, tmp_path / "failed.html")


def test_reviewer_budget_is_preserved_by_cli_resume(workflow, monkeypatch):
    original = workflow["llm"]
    def models(rules, prompt, schema):
        if schema is FindingReview:
            result = reviewer(prompt)
            result.claims[0].verdict = "insufficient"
            return result
        if "validation_failures" in prompt:
            raise TimeoutError()
        return original(rules, prompt, schema)
    monkeypatch.setattr(pipeline, "llm_parse", models)
    assert cli(monkeypatch, ["review", "--assessment-id", "demo", "--limit", "1"]) == 0
    before = workflow["store"].load()
    assert before.sections["R1"].repair_attempts == 1
    assert before.sections["R1"].finding.status == "needs_review"
    calls = copy.deepcopy(before.sections["R1"].model_calls)
    assert cli(monkeypatch, ["review", "--assessment-id", "demo", "--resume", "--limit", "1"]) == 0
    assert workflow["store"].load().sections["R1"].model_calls == calls


def test_role_boundaries_reject_cross_role_operations():
    role = AssessmentOrchestrator()
    with pytest.raises(ValueError):
        role.evidence_retriever.run("draft", lambda: pytest.fail("Cross-role work"), None, lambda: None)
    with pytest.raises(ValueError):
        role.evidence_reviewer.run("retrieval", lambda: pytest.fail("Cross-role work"), None)
