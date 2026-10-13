"""Synthetic persistence tests: no user corpus, index or model calls."""
import json
from pathlib import Path

import pytest

from mdr_rag import pipeline, report_state, review_state
from mdr_rag.report_state import StateStore, export_report, import_legacy
from mdr_rag.requirement_identity import assign_identity
from mdr_rag.schemas import Finding, FindingClaim, QuotedReference


def requirement(key):
    return {"id": key, "requirement": f"Maintain records for {key}",
            "exact_quote": f"The manufacturer shall maintain records for {key}.",
            "provision": "Annex I", "applies_to": "manufacturer",
            "legal_source_chunk_id": "L-1", "legal_source": "legal/law.pdf",
            "legal_page": 1, "legal_sha256": "law-hash", "human_validated": False}


@pytest.fixture
def workflow(monkeypatch, tmp_path):
    monkeypatch.setenv("MULTI_QUERY_ENABLED", "false")
    state_root = tmp_path / "state"
    state_root.mkdir()
    draft = {"requirements": [requirement(key) for key in ("R1", "R2", "R3")],
             "source": "legal/law.pdf", "source_sha256": "law-hash",
             "legal_version_label": "Synthetic historical law", "selected_pdf_pages": [1],
             "unreadable_selected_pages": [], "rejected_unverifiable_quotes": []}
    draft_path = state_root / "requirements_draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    manifest = {"embedding_model": "embeddinggemma", "files": [
        {"source": "legal/law.pdf", "sha256": "law-hash", "kind": "legal", "chunks": 1},
        {"source": "device/records.txt", "sha256": "device-hash", "kind": "device", "chunks": 1}]}
    profile = {"device_name": "Synthetic"}
    monkeypatch.setattr(pipeline, "STATE", state_root)
    monkeypatch.setattr(pipeline, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(pipeline, "check_manifest", lambda: manifest)
    monkeypatch.setattr(pipeline, "check_regulation_alignment", lambda draft: None)
    monkeypatch.setattr(pipeline, "profile_data", lambda: profile)
    monkeypatch.setattr(pipeline, "legal_chunks", lambda source, pages: [{
        "id": "L-1", "text": "\n".join(req["exact_quote"] for req in draft["requirements"]),
        "meta": {"source": "legal/law.pdf", "sha256": "law-hash", "kind": "legal", "page": 1, "block": 1}}])
    original_extract = pipeline.extract_requirements
    monkeypatch.setattr(pipeline, "extract_requirements", lambda *args: pytest.fail("Resume must not extract"))
    for key, value in {"OLLAMA_LLM_MODEL": "qwen3:4b", "EMBEDDING_MODEL": "embeddinggemma",
                       "OLLAMA_NUM_CTX": "8192", "RETRIEVAL_MODE": "hybrid",
                       "RERANK_ENABLED": "false"}.items():
        monkeypatch.setenv(key, value)
    calls = {"retrieval": [], "llm": []}

    def retrieval(query, kind, k):
        calls["retrieval"].append((query, k))
        return [{"id": "D-1", "text": "Synthetic maintenance records", "meta": {
            "source": "device/records.txt", "sha256": "device-hash", "page": 0,
            "block": 1, "kind": "device"}}]

    def llm(rules, prompt, schema):
        calls["llm"].append(prompt)
        return Finding(status="supported", explanation="Synthetic evidence only", evidence_ids=["D-1"],
                       missing_information=[], recommended_actions=[], applicability_reason="Unverified",
                       claims=[FindingClaim(claim_id="C1", text="Synthetic evidence only", evidence=[
                           QuotedReference(source_id="D-1", exact_quote="Synthetic maintenance records")])])

    monkeypatch.setattr(pipeline, "hybrid_search", retrieval)
    monkeypatch.setattr(pipeline, "llm_parse", llm)
    return {"root": state_root, "draft": draft, "draft_path": draft_path,
            "manifest": manifest, "profile": profile, "calls": calls, "llm": llm,
            "extract": original_extract,
            "store": StateStore(state_root, "demo"), "reports": tmp_path / "reports"}


def test_interrupted_run_resumes_from_retrieval_checkpoint(workflow, monkeypatch):
    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(pipeline, "llm_parse", interrupt)
    with pytest.raises(KeyboardInterrupt):
        pipeline.run_review(assessment_id="demo", limit=1, k=4)
    saved = workflow["store"].load()
    assert saved.sections["R1"].checkpoint == "retrieval"
    assert saved.sections["R1"].execution_status == "running"
    assert len(workflow["calls"]["retrieval"]) == 1
    monkeypatch.setattr(pipeline, "llm_parse", workflow["llm"])
    final = pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert len(workflow["calls"]["retrieval"]) == 1
    assert final.sections["R1"].execution_status == "completed"
    assert final.config["k"] == 4
    assert final.partial_run
    assert final.execution_counts == {"completed": 1, "pending": 2}
    assert len(list((workflow["store"].directory / "revisions").glob("*.json"))) == final.revision


def test_failed_draft_keeps_last_checkpoint_and_resumes(workflow, monkeypatch):
    def fail(*args):
        raise RuntimeError("private document snippet must not be persisted")

    monkeypatch.setattr(pipeline, "llm_parse", fail)
    with pytest.raises(RuntimeError):
        pipeline.run_review(assessment_id="demo", limit=1)
    saved = workflow["store"].load()
    assert saved.sections["R1"].execution_status == "failed"
    assert saved.sections["R1"].checkpoint == "retrieval"
    assert "private document" not in workflow["store"].path.read_text()
    monkeypatch.setattr(pipeline, "llm_parse", workflow["llm"])
    final = pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert len(workflow["calls"]["retrieval"]) == 1
    assert final.sections["R1"].attempt_count == 2


def test_interruption_after_draft_does_not_repeat_generation(workflow, monkeypatch):
    original = pipeline.validate_ids

    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(pipeline, "validate_ids", interrupt)
    with pytest.raises(KeyboardInterrupt):
        pipeline.run_review(assessment_id="demo", limit=1)
    assert workflow["store"].load().sections["R1"].checkpoint == "draft"
    monkeypatch.setattr(pipeline, "validate_ids", original)
    final = pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert final.sections["R1"].execution_status == "completed"
    assert len(workflow["calls"]["llm"]) == 1


def test_checkpoint_write_failure_resumes_from_last_committed_stage(workflow, monkeypatch):
    original = report_state.os.replace
    interrupted = False

    def fail_draft_write(source, destination):
        nonlocal interrupted
        if Path(destination) == workflow["store"].path:
            payload = json.loads(Path(source).read_text(encoding="utf-8"))
            if payload["sections"]["R1"]["checkpoint"] == "draft" and not interrupted:
                interrupted = True
                raise OSError("interrupted draft checkpoint replacement")
        original(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(report_state.os, "replace", fail_draft_write)
        with pytest.raises(OSError):
            pipeline.run_review(assessment_id="demo", limit=1)
    assert workflow["store"].load().sections["R1"].checkpoint == "retrieval"
    final = pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert final.sections["R1"].execution_status == "completed"
    assert len(workflow["calls"]["retrieval"]) == 1
    assert len(workflow["calls"]["llm"]) == 2  # Uncommitted draft must be regenerated.


def test_history_write_interruption_recovers_from_committed_canonical_state(workflow, monkeypatch):
    original = report_state.atomic_write

    def fail_draft_history(destination, text):
        if Path(destination).parent.name == "revisions":
            payload = json.loads(text)
            if payload["sections"]["R1"]["checkpoint"] == "draft":
                raise OSError("simulated history write interruption")
        original(destination, text)

    with monkeypatch.context() as patch:
        patch.setattr(report_state, "atomic_write", fail_draft_history)
        with pytest.raises(OSError):
            pipeline.run_review(assessment_id="demo", limit=1)
    committed = workflow["store"].load()
    assert committed.sections["R1"].checkpoint == "draft"
    assert not (workflow["store"].directory / "revisions" / f"{committed.revision:08d}.json").exists()
    assert review_state.render_report("demo", historical=True, revision=committed.revision)["historical_snapshot"]
    final = pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert final.sections["R1"].execution_status == "completed"
    assert len(workflow["calls"]["llm"]) == 1
    assert len(list((workflow["store"].directory / "revisions").glob("*.json"))) == final.revision


def test_targeted_refresh_preserves_other_sections_exactly(workflow):
    before = pipeline.run_review(assessment_id="demo")
    after = pipeline.run_review(assessment_id="demo", requirement_id="R2", refresh=True)
    for key in ("R1", "R3"):
        assert before.sections[key].model_dump() == after.sections[key].model_dump()
    assert after.sections["R2"].revision == 2
    assert len(after.sections["R2"].finding_history) == 2
    assert len(workflow["calls"]["retrieval"]) == 4
    assert len(workflow["calls"]["llm"]) == 4
    exported = json.loads((workflow["reports"] / "assessment.json").read_text())
    assert exported["assessed_requirements"] == 3
    assert not exported["partial_run"]


def test_requirement_edit_retrieves_only_affected_section(workflow):
    before = pipeline.run_review(assessment_id="demo")
    workflow["draft"]["requirements"][1]["requirement"] = "Updated R2 wording"
    workflow["draft_path"].write_text(json.dumps(workflow["draft"]))
    after = pipeline.run_review(assessment_id="demo", resume=True)
    assert len(workflow["calls"]["retrieval"]) == 4
    assert len(workflow["calls"]["llm"]) == 4
    assert after.sections["R2"].revision == 2
    assert after.sections["R1"].model_dump() == before.sections["R1"].model_dump()
    assert after.sections["R3"].model_dump() == before.sections["R3"].model_dump()


@pytest.mark.parametrize("change,retained", [
    ("profile", "pending"), ("corpus", "queries"), ("retrieval", "queries"),
    ("review", "retrieval"), ("validation", "draft"), ("query", "applicability")])
def test_dependencies_invalidate_at_earliest_affected_stage(workflow, change, retained):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    section = state.sections["R1"]
    published = section.finding.model_dump()
    dep = section.dependencies.model_copy(update={change: "changed"})
    assert report_state.invalidate(section, dep)
    assert section.checkpoint == retained
    assert section.execution_status == "stale"
    assert section.finding.model_dump() == published
    assert section.revision == 1
    assert report_state.compatibility_report(state)["findings"] == []
    assert report_state.compatibility_report(state, historical=True)["historical_snapshot"]


def test_uncited_new_corpus_file_invalidates_all_sections(workflow):
    pipeline.run_review(assessment_id="demo")
    workflow["manifest"]["files"].append({"kind": "device", "source": "device/new.txt",
                                          "sha256": "new", "chunks": 1})
    after = pipeline.run_review(assessment_id="demo", requirement_id="R2")
    assert after.sections["R1"].execution_status == "stale"
    assert after.sections["R3"].execution_status == "stale"
    assert after.sections["R2"].execution_status == "completed"
    assert len(workflow["calls"]["retrieval"]) == 4
    assert after.partial_run
    report = report_state.compatibility_report(after)
    assert report["assessed_requirements"] == 1
    assert report["sections"]["R1"]["stale_reasons"] == ["corpus"]


def test_model_change_redrafts_without_retrieving(workflow, monkeypatch):
    pipeline.run_review(assessment_id="demo")
    monkeypatch.setenv("OLLAMA_LLM_MODEL", "synthetic-new-model")
    pipeline.run_review(assessment_id="demo", resume=True)
    assert len(workflow["calls"]["retrieval"]) == 3
    assert len(workflow["calls"]["llm"]) == 6


def test_prompt_change_invalidates_draft_but_reuses_retrieval(workflow, monkeypatch):
    pipeline.run_review(assessment_id="demo")
    monkeypatch.setattr(review_state, "REVIEW_INPUT", review_state.REVIEW_INPUT + "\nUpdated instructions")
    pipeline.run_review(assessment_id="demo", resume=True)
    assert len(workflow["calls"]["retrieval"]) == 3
    assert len(workflow["calls"]["llm"]) == 6


def test_saved_k_override_invalidates_all_retrieval_dependencies(workflow):
    pipeline.run_review(assessment_id="demo", k=3)
    after = pipeline.run_review(assessment_id="demo", requirement_id="R2", k=5)
    assert after.sections["R1"].execution_status == "stale"
    assert after.sections["R3"].execution_status == "stale"
    assert workflow["calls"]["retrieval"][-1][1] == 5
    assert len(workflow["calls"]["retrieval"]) == 4


def test_unindexed_source_change_persists_stale_state_without_inference(workflow, monkeypatch):
    pipeline.run_review(assessment_id="demo")

    def invalid_manifest():
        raise RuntimeError("File changed since indexing")

    monkeypatch.setattr(pipeline, "check_manifest", invalid_manifest)
    with pytest.raises(RuntimeError, match="saved findings are stale"):
        pipeline.run_review(assessment_id="demo", resume=True)
    assert all(s.execution_status == "stale" for s in workflow["store"].load().sections.values())
    assert len(workflow["calls"]["llm"]) == 3


def test_locks_and_expected_revisions_prevent_lost_updates(workflow):
    initial = pipeline.run_review(assessment_id="demo", limit=1)
    first = workflow["store"]
    other = StateStore(workflow["root"], "demo")
    with first.locked():
        with pytest.raises(RuntimeError, match="Wait for the other process"):
            with other.locked():
                pytest.fail("A second writer acquired the lock")
        newer = first.save(initial, initial.revision)
    bytes_before = first.path.read_bytes()
    with other.locked(), pytest.raises(RuntimeError, match="revision conflict"):
        other.save(initial, initial.revision)
    assert other.path.read_bytes() == bytes_before
    assert other.load().revision == newer.revision
    with pytest.raises(RuntimeError, match="requires the assessment lock"):
        other.save(newer, newer.revision)


def test_lock_rejects_a_separate_process(workflow):
    import subprocess
    import sys

    script = (
        "from pathlib import Path; from mdr_rag.report_state import StateStore; import sys\n"
        "try:\n"
        "    with StateStore(Path(sys.argv[1]), 'demo').locked(): pass\n"
        "except RuntimeError as exc:\n"
        "    print(str(exc)); sys.exit(3)\n"
    )
    with workflow["store"].locked():
        result = subprocess.run([sys.executable, "-c", script, str(workflow["root"])],
                                capture_output=True, text=True, timeout=20)
    assert result.returncode == 3
    assert "Assessment lock conflict" in result.stdout


@pytest.mark.parametrize("corruption", ['{broken json', '{"schema_version": 99}', '{"schema_version": 1}'])
def test_malformed_state_never_overwritten(workflow, corruption):
    store = workflow["store"]
    store.directory.mkdir(parents=True)
    store.path.write_text(corruption)
    original = store.path.read_bytes()
    with pytest.raises(RuntimeError, match="Invalid assessment state"):
        pipeline.run_review(assessment_id="demo", resume=True)
    assert store.path.read_bytes() == original
    assert workflow["calls"] == {"retrieval": [], "llm": []}


def test_atomic_replace_failure_keeps_previous_state_and_allows_retry(workflow, monkeypatch):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    store = workflow["store"]
    original = store.path.read_bytes()
    original_replace = report_state.os.replace

    def fail_canonical(source, destination):
        assert Path(source).parent == Path(destination).parent
        if Path(destination) == store.path:
            raise OSError("simulated replacement interruption")
        original_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(report_state.os, "replace", fail_canonical)
        with store.locked(), pytest.raises(OSError):
            store.save(state, state.revision)
    assert store.path.read_bytes() == original
    assert not list(store.directory.glob(".assessment-*.tmp"))
    with store.locked():
        committed = store.save(state, state.revision)
    assert committed.revision == state.revision + 1


def test_legacy_import_preserves_ids_status_and_limitations(workflow):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    legacy = report_state.compatibility_report(state)
    legacy["limitations"] = ["Original audit limitation"]
    legacy["human_validated"] = True  # Must never be promoted by import.
    source = workflow["reports"] / "legacy.json"
    source.write_text(json.dumps(legacy), encoding="utf-8")
    original = source.read_bytes()
    migrated = import_legacy(source, workflow["root"], "imported")
    assert source.read_bytes() == original
    assert list(migrated.sections) == ["R1"]
    assert migrated.sections["R1"].finding == state.sections["R1"].finding
    assert migrated.sections["R1"].audit_status == "legacy_unverified"
    assert migrated.sections["R1"].dependencies is None
    assert not migrated.human_validated
    assert "Original audit limitation" in migrated.limitations
    assert migrated.partial_run
    assert report_state.compatibility_report(migrated)["total_extracted_requirements"] == 3
    with pytest.raises(RuntimeError, match="already exists"):
        import_legacy(source, workflow["root"], "imported")
    with pytest.raises(RuntimeError, match="lack dependency validation"):
        review_state.render_report("imported")
    historical = review_state.render_report("imported", historical=True)
    assert historical["findings"][0]["audit_status"] == "legacy_unverified"
    assert historical["historical_snapshot"]


def test_partial_legacy_resume_integrates_register_without_double_counting(workflow):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    source = workflow["reports"] / "legacy-partial.json"
    source.write_text(json.dumps(report_state.compatibility_report(state)))
    import_legacy(source, workflow["root"], "imported")
    after = pipeline.run_review(assessment_id="imported", resume=True)
    report = report_state.compatibility_report(after)
    assert report["total_extracted_requirements"] == 3
    assert report["assessed_requirements"] == 3
    assert not after.partial_run
    assert after.sections["R1"].revision == 2
    assert after.sections["R1"].finding_history[0]["revision"] == 1
    assert all(s.audit_status == "raw_spans_checked" for s in after.sections.values())
    assert any("Imported legacy report" in limitation for limitation in after.limitations)


def test_legacy_missing_citation_remains_explicitly_unverified(workflow):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    legacy = report_state.compatibility_report(state)
    legacy["findings"][0]["finding"]["evidence_ids"] = ["D-missing"]
    source = workflow["reports"] / "legacy-invalid-citation.json"
    source.write_text(json.dumps(legacy))
    migrated = import_legacy(source, workflow["root"], "imported")
    destination = workflow["root"] / "import-preview"
    export_report(migrated, destination, historical=True)
    assert migrated.sections["R1"].finding.evidence_ids == ["D-missing"]
    assert "UNVERIFIED: missing" in (destination / "assessment.md").read_text(encoding="utf-8")


def test_historical_revision_render_does_not_use_live_sources_or_mutate_state(workflow, monkeypatch):
    before = pipeline.run_review(assessment_id="demo", limit=1)
    original = workflow["store"].path.read_bytes()
    monkeypatch.setattr(pipeline, "check_manifest", lambda: pytest.fail("Historical render touched live corpus"))
    report = review_state.render_report("demo", historical=True, revision=before.revision)
    assert report["historical_snapshot"]
    assert workflow["store"].path.read_bytes() == original
    markdown = (workflow["store"].directory / f"historical-{before.revision}" / "assessment.md").read_text(encoding="utf-8")
    assert "HISTORICAL" in markdown


def test_current_render_detects_profile_change_without_model_calls(workflow):
    pipeline.run_review(assessment_id="demo")
    workflow["profile"]["classification"] = "changed unverified fact"
    report = review_state.render_report("demo")
    assert report["partial_run"]
    assert report["findings"] == []
    assert all(s["checkpoint"] == "pending" for s in report["sections"].values())
    assert len(workflow["calls"]["llm"]) == 3


def test_paraphrases_keep_deterministic_id_and_create_requirement_revision():
    req = requirement("unused")
    text = "Introduction. " + req["exact_quote"]
    first = assign_identity(req, text, [])
    rewritten = dict(req, requirement="Paraphrase of the same anchored duty")
    independent = assign_identity(rewritten, text, [])
    assert first["id"] == independent["id"]
    updated = assign_identity(rewritten, text, [first])
    assert updated["id"] == first["id"]
    assert updated["requirement_revision"] == 2
    assert updated["requirement_history"][0]["requirement"] == first["requirement"]
    legacy = dict(first, id="R-legacy")
    assert assign_identity(rewritten, text, [legacy])["id"] == "R-legacy"


@pytest.mark.parametrize("options", [
    {"limit": 0}, {"k": -1}, {"assessment_id": "../escape"},
    {"resume": True}, {"refresh": True}, {"requirement_id": "R1"},
    {"assessment_id": "demo", "requirement_id": "R1", "limit": 1},
    {"assessment_id": "demo", "requirement_id": "R1", "resume": True, "refresh": True}])
def test_invalid_run_options_do_not_create_assessment(workflow, options):
    with pytest.raises(ValueError):
        pipeline.run_review(**options)
    assert not workflow["store"].path.exists()
    assert workflow["calls"] == {"retrieval": [], "llm": []}


def test_cli_passes_persistence_options_without_inference(monkeypatch):
    import main

    calls = []
    monkeypatch.setattr(main, "run_review", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr("sys.argv", ["main.py", "review", "--assessment-id", "demo",
                                     "--requirement-id", "R2", "--refresh"])
    assert main.main() == 0
    assert calls == [((None, None), {"assessment_id": "demo", "requirement_id": "R2",
                                    "refresh": True, "resume": False})]
