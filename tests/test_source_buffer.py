"""Raw provenance tests use synthetic text, mocked models and isolated stores."""
import json
from pathlib import Path

import pytest

from mdr_rag import core, pipeline, report_state, review_state, search
from mdr_rag.schemas import FindingReview, Finding, FindingClaim, QuotedReference, RequirementBatch, RequirementCandidate
from mdr_rag.source_buffer import (
    ACTIVE_RECORDER, EvidenceRun, SourceBuffer, call_trace, normalized_offsets, recording,
)
from test_report_state import workflow, structured, reviewer, ask_fixture  # Reuse the isolated synthetic workflow fixture.


def record(text="Synthetic maintenance records", *, key="D-1", kind="device", source=None,
           sha="fixture-file-hash", page=0, block=1):
    return {"id": key, "text": text, "meta": {"kind": kind, "source": source or f"{kind}/records.txt",
            "sha256": sha, "page": page, "block": block}}


def claim_finding(quote="Synthetic maintenance records", *, source_id="D-1", offsets=None):
    return structured(Finding(status="supported", explanation="Synthetic claim", evidence_ids=[source_id],
                   missing_information=[], recommended_actions=[], applicability_reason="Unverified",
                   claims=[FindingClaim(claim_id="C1", text="Synthetic claim", evidence=[QuotedReference(
                       source_id=source_id, exact_quote=quote, start=offsets[0] if offsets else None,
                       end=offsets[1] if offsets else None)])]))


def test_snapshots_are_content_addressed_frozen_and_persistent(tmp_path):
    buffer = SourceBuffer(directory=tmp_path / "buffer")
    key = buffer.add_passage(record())
    saved = buffer.get_passage(key)
    original = (tmp_path / "buffer" / (key + ".json")).read_bytes()
    assert buffer.add_passage(record()) == key
    assert (tmp_path / "buffer" / (key + ".json")).read_bytes() == original
    assert SourceBuffer(directory=tmp_path / "buffer").get_passage(key) == saved
    with pytest.raises(ValueError):
        saved.text = "mutated"
    copy = buffer.snapshots
    copy.clear()
    assert buffer.get_passage(key) == saved


@pytest.mark.parametrize("buffer_id", ["invented", "SB-" + "0" * 64, "../../secret"])
def test_invented_or_unsafe_buffer_ids_are_rejected(buffer_id):
    with pytest.raises(ValueError):
        SourceBuffer().get_passage(buffer_id)


def test_quotes_must_belong_to_the_linked_passage():
    buffer = SourceBuffer()
    first = buffer.add_passage(record("alpha evidence", key="D-a"))
    second = buffer.add_passage(record("beta evidence", key="D-b"))
    link = buffer.make_link(buffer.resolve_quote(first, "alpha evidence"), "C1", "device_support")
    with pytest.raises(ValueError):
        buffer.validate_link(link.model_copy(update={"buffer_id": second}))
    with pytest.raises(ValueError):
        buffer.resolve_quote(second, "alpha evidence")


@pytest.mark.parametrize("field,value", [("file_sha256", "wrong"), ("text_sha256", "wrong"),
    ("source", "device/wrong.txt"), ("page", 1), ("block", 2), ("chunk_id", "invented"),
    ("kind", "legal"), ("locator", "pdf_page"), ("start", 1), ("end", 999)])
def test_links_reject_wrong_hash_identity_location_or_span(field, value):
    buffer = SourceBuffer()
    key = buffer.add_passage(record())
    link = buffer.make_link(buffer.resolve_quote(key, "maintenance records"), "C1", "device_support")
    with pytest.raises(ValueError):
        buffer.validate_link(link.model_copy(update={field: value}))


def test_changed_file_and_text_create_new_snapshot_without_overwriting_old(tmp_path):
    buffer = SourceBuffer(directory=tmp_path)
    old = buffer.add_passage(record())
    old_bytes = (tmp_path / (old + ".json")).read_bytes()
    link = buffer.make_link(buffer.resolve_quote(old, "maintenance records"), "C1", "device_support")
    new = buffer.add_passage(record("Updated records", sha="updated-file-hash"))
    assert new != old
    assert (tmp_path / (old + ".json")).read_bytes() == old_bytes
    assert buffer.validate_link(link)
    assert buffer.get_passage(old).text == "Synthetic maintenance records"
    assert buffer.add_passage(record(), extraction_version="new-parser") != old
    assert buffer.add_passage(record(), index_version="new-index-format") != old


def test_tampered_snapshot_is_rejected_without_overwriting_it(tmp_path):
    buffer = SourceBuffer(directory=tmp_path)
    key = buffer.add_passage(record())
    path = tmp_path / (key + ".json")
    data = json.loads(path.read_text())
    data["text"] = "corrupted"
    path.write_text(json.dumps(data))
    corrupted = path.read_bytes()
    with pytest.raises(ValueError):
        SourceBuffer(directory=tmp_path).get_passage(key)
    with pytest.raises(ValueError):
        buffer.add_passage(record())
    assert path.read_bytes() == corrupted


def test_repeated_quotes_require_explicit_chosen_offsets():
    buffer = SourceBuffer()
    key = buffer.add_passage(record("records and records"))
    with pytest.raises(ValueError, match="Ambiguous"):
        buffer.resolve_quote(key, "records")
    span = buffer.resolve_quote(key, "records", (12, 19))
    assert span.start == 12
    assert buffer.validate_link(buffer.make_link(span, "C1", "device_support"))
    with pytest.raises(ValueError):
        buffer.resolve_quote(key, "records", (1, 8))


def test_overlapping_chunks_remain_distinct_and_traceable():
    buffer = SourceBuffer()
    first = buffer.add_passage(record("intro shared evidence", key="D-a", block=1))
    second = buffer.add_passage(record("shared evidence conclusion", key="D-b", block=2))
    assert first != second
    a = buffer.make_link(buffer.resolve_quote(first, "shared evidence"), "C1", "device_support")
    b = buffer.make_link(buffer.resolve_quote(second, "shared evidence"), "C1", "device_support")
    assert a.start == 6 and b.start == 0
    assert buffer.validate_link(a) and buffer.validate_link(b)


def test_pdf_page_and_docx_block_locators_remain_distinct():
    buffer = SourceBuffer()
    pdf = buffer.add_passage(record(source="device/records.pdf", page=4))
    docx = buffer.add_passage(record(source="device/records.docx", block=1001))
    assert buffer.get_passage(pdf).locator == "pdf_page"
    assert buffer.get_passage(docx).locator == "text_block"
    with pytest.raises(ValueError):
        buffer.add_passage(record(source="device/records.docx", page=4))
    with pytest.raises(ValueError):
        buffer.add_passage(record(source="device/records.pdf", page=0))


@pytest.mark.parametrize("raw", [
    "Must provide risk management\n  documentation.",
    "Must provide RISK MANAGEMENT documentation.",
    "Must provide risk\u00ad management documentation.",
    "Must provide risk‐management documentation.",
    "The STRAßE documentation is required.",
])
def test_legacy_normalization_maps_back_to_exact_raw_characters(raw):
    buffer = SourceBuffer()
    key = buffer.add_passage(record(raw))
    normalized = core.norm(raw)
    assert normalized_offsets(raw)[0] == normalized
    span = buffer.resolve_legacy_quote(key, normalized)
    assert span.exact_quote == raw
    assert buffer.get_passage(key).text[span.start:span.end] == span.exact_quote
    assert buffer.validate_link(buffer.make_link(span, "R1", "applicability"))
    assert core.is_real_quote(normalized, raw)  # Existing normalized validator is retained.


def test_ambiguous_normalized_mapping_requires_offsets():
    buffer = SourceBuffer()
    text = "Risk\n records; RISK records"
    key = buffer.add_passage(record(text))
    with pytest.raises(ValueError, match="Ambiguous"):
        buffer.resolve_legacy_quote(key, "risk records")
    span = buffer.resolve_legacy_quote(key, "risk records", (0, 13))
    assert span.exact_quote == "Risk\n records"


def test_raw_links_do_not_use_the_legacy_normalization_shortcut():
    buffer = SourceBuffer()
    text = "Must maintain risk\n management documentation"
    key = buffer.add_passage(record(text))
    quote = "maintain risk management documentation"
    assert core.is_real_quote(quote, text)
    assert not core.is_raw_quote(quote, text)
    with pytest.raises(ValueError):
        buffer.resolve_quote(key, quote)
    assert buffer.resolve_legacy_quote(key, quote).exact_quote == "maintain risk\n management documentation"


def test_claim_span_must_be_inside_the_presented_range():
    buffer = SourceBuffer()
    key = buffer.add_passage(record("prefix seen evidence; unseen evidence"))
    shown = [buffer.presented(key, end=20)]
    link = buffer.make_link(buffer.resolve_quote(key, "unseen evidence"), "C1", "device_support")
    assert buffer.validate_link(link)
    with pytest.raises(ValueError, match="not presented"):
        buffer.validate_link(link, presented=shown)


def test_call_trace_rejects_spans_absent_from_actual_input():
    buffer = SourceBuffer()
    key = buffer.add_passage(record())
    with pytest.raises(ValueError, match="absent from the actual model input"):
        call_trace(buffer, "draft", "mock", "rules", "D-1: different text", [key], [buffer.presented(key)])


def test_failed_reranking_keeps_the_pre_inference_trace(tmp_path, monkeypatch):
    import ollama

    run = EvidenceRun(tmp_path, "rerank-test")

    def failure(**kwargs):
        raise RuntimeError("private source excerpt in provider exception")

    monkeypatch.setattr(ollama, "chat", failure)
    with recording(run.recorder), pytest.raises(RuntimeError):
        search.rerank_passages("synthetic query", [record()])
    trace = json.loads(run.path.read_text())
    assert trace["model_calls"][0]["outcome"] == "failed"
    assert len(trace["model_calls"][0]["presented"]) == 1
    assert "private source excerpt" not in run.path.read_text()


def test_answer_abstains_on_a_normalized_but_non_raw_quote(tmp_path, monkeypatch, capsys):
    from mdr_rag.schemas import Answer, AnswerClaim, AnswerSupportVerification, ClaimEvidence

    source = record("Manufacturer must maintain\n risk records.", key="L-1", kind="legal",
                    source="legal/law.pdf", page=1)
    monkeypatch.setattr(pipeline, "STATE", tmp_path / "state")
    monkeypatch.setattr(pipeline, "check_manifest", lambda: {})
    monkeypatch.setattr(pipeline, "hybrid_search", lambda query, kind, k: [source] if kind == "legal" else [])
    responses = iter([Answer(answer="A claim", source_ids=["L-1"], limitations=[]),
        AnswerSupportVerification(claims=[AnswerClaim(claim="A claim", supported=True, evidence=[
            ClaimEvidence(source_id="L-1", exact_quote="maintain risk records")])])])
    monkeypatch.setattr(pipeline, "llm_parse", lambda rules, prompt, schema: ask_fixture(next(responses), prompt, quote="Manufacturer must maintain\n risk records."))
    pipeline.run_ask("Synthetic question")
    assert "Insufficient evidence to provide a fully source-supported answer" in capsys.readouterr().out
    ledger = json.loads(next((tmp_path / "state" / "evidence_runs").glob("ask-*/trace.json")).read_text())
    assert ledger["publication_status"] == "abstained"
    assert not ledger["links"]


def test_three_evidence_sets_are_saved_separately(workflow, monkeypatch):
    records = [record(key=key, block=n, text="Synthetic maintenance records" if n == 1 else f"Unused {n}",
                      sha="device-hash") for n, key in enumerate(("D-1", "D-2", "D-3"), 1)]

    def retrieve(query, kind, k):
        ACTIVE_RECORDER.get().record_retrieved(records)
        return records[:2]

    monkeypatch.setattr(pipeline, "hybrid_search", retrieve)
    state = pipeline.run_review(assessment_id="demo", limit=1)
    section = state.sections["R1"]
    assert len(section.retrieved_buffer_ids) == 3
    draft_call = next(call for call in section.model_calls if call.stage == "review_draft")
    shown_device = {p.buffer_id for p in draft_call.presented if state.source_buffer[p.buffer_id].kind == "device"}
    assert len(shown_device) == 2
    assert len(section.claim_links) == 1
    assert section.claim_links[0].chunk_id == "D-1"
    assert section.legal_anchor.kind == "legal"
    assert section.finding.status == "supported"
    assert section.audit_status == "semantic_checked"


def test_retrieved_hash_mismatch_fails_before_drafting(workflow, monkeypatch):
    monkeypatch.setattr(pipeline, "hybrid_search", lambda *args, **kwargs: [record(sha="wrong-file-hash")])
    with pytest.raises(ValueError, match="differs from the validated manifest"):
        pipeline.run_review(assessment_id="demo", limit=1)
    assert not workflow["calls"]["llm"]
    section = workflow["store"].load().sections["R1"]
    assert section.execution_status == "failed"
    assert section.checkpoint == "queries"


@pytest.mark.parametrize("quote,source", [
    ("invented text", "D-1"), ("Synthetic maintenance records", "D-invented"),
    ("Synthetic  maintenance records", "D-1")])
def test_invalid_claim_quotes_are_not_published_as_verified_evidence(workflow, monkeypatch, quote, source):
    monkeypatch.setattr(pipeline, "llm_parse", lambda rules, prompt, schema: reviewer(prompt) if schema is FindingReview else claim_finding(quote, source_id=source))
    state = pipeline.run_review(assessment_id="demo", limit=1)
    section = state.sections["R1"]
    assert section.finding.status == "needs_review"
    assert not section.claim_links
    assert not section.finding.claims
    assert not section.finding.evidence_ids
    assert section.draft_finding.claims[0].evidence[0].exact_quote == quote


def test_quote_outside_truncated_model_context_is_rejected(workflow, monkeypatch):
    long_text = "a" * 2250 + " unseen maintenance evidence"
    monkeypatch.setattr(pipeline, "hybrid_search", lambda *args, **kwargs: [record(long_text, sha="device-hash")])
    monkeypatch.setattr(pipeline, "llm_parse", lambda rules, prompt, schema: reviewer(prompt) if schema is FindingReview else claim_finding("unseen maintenance evidence"))
    state = pipeline.run_review(assessment_id="demo", limit=1)
    section = state.sections["R1"]
    assert section.finding.status == "needs_review"
    trace = next(item for item in section.model_calls if item.stage == "review_draft")
    assert next(p for p in trace.presented if state.source_buffer[p.buffer_id].kind == "device").end == 2200


def test_repeated_claim_quote_requires_model_offsets(workflow, monkeypatch):
    text = "Synthetic maintenance records. Synthetic maintenance records."
    monkeypatch.setattr(pipeline, "hybrid_search", lambda *args, **kwargs: [record(text, sha="device-hash")])
    bad = pipeline.run_review(assessment_id="demo", limit=1)
    assert bad.sections["R1"].finding.status == "needs_review"
    start = text.rfind("Synthetic maintenance records")
    monkeypatch.setattr(pipeline, "llm_parse", lambda rules, prompt, schema: reviewer(prompt) if schema is FindingReview else claim_finding(offsets=(start, start + 29)))
    good = pipeline.run_review(assessment_id="demo", requirement_id="R1", refresh=True)
    assert good.sections["R1"].finding.status == "supported"
    assert good.sections["R1"].claim_links[0].start == start


def test_unmappable_legal_quote_is_flagged_and_never_rendered_as_exact(workflow, monkeypatch):
    monkeypatch.setattr(pipeline, "legal_chunks", lambda *args: [record("Unrelated legal passage", key="L-1",
        kind="legal", source="legal/law.pdf", sha="law-hash", page=1)])
    state = pipeline.run_review(assessment_id="demo", limit=1)
    assert state.sections["R1"].legal_anchor is None
    assert state.sections["R1"].finding.status == "needs_review"
    report = report_state.compatibility_report(state)
    assert report["findings"][0]["requirement"]["exact_quote"] == ""
    assert not report["findings"][0]["legal_quote_verified"]
    markdown = (workflow["store"].directory / "assessment.md").read_text(encoding="utf-8")
    assert "Raw span unverified" in markdown


def test_legacy_legal_anchor_maps_to_raw_quote_without_changing_register(workflow, monkeypatch):
    raw = workflow["draft"]["requirements"][0]["exact_quote"].replace("maintain records", "maintain\n records")
    original = workflow["draft_path"].read_bytes()
    monkeypatch.setattr(pipeline, "legal_chunks", lambda *args: [record(raw, key="L-1", kind="legal",
        source="legal/law.pdf", sha="law-hash", page=1)])
    state = pipeline.run_review(assessment_id="demo", limit=1)
    assert state.sections["R1"].legal_anchor.exact_quote == raw
    assert state.sections["R1"].legal_anchor.resolution == "legacy_normalized_mapping"
    assert workflow["draft_path"].read_bytes() == original
    report = report_state.compatibility_report(state)
    assert report["findings"][0]["requirement"]["exact_quote"] == raw
    assert raw in (workflow["store"].directory / "assessment.md").read_text(encoding="utf-8")


def test_old_snapshot_reproduces_report_after_reindex_and_source_changes(workflow, monkeypatch):
    first = pipeline.run_review(assessment_id="demo", limit=1)
    historical_before = review_state.render_report("demo", historical=True, revision=first.revision)
    path = workflow["store"].directory / f"historical-{first.revision}" / "assessment.md"
    markdown_before = path.read_bytes()
    old_buffer = {key: value.model_dump() for key, value in first.source_buffer.items()}
    workflow["manifest"]["files"][1]["sha256"] = "changed-file-hash"
    monkeypatch.setattr(pipeline, "hybrid_search", lambda *args, **kwargs: [record("Updated source", sha="changed-file-hash")])
    pipeline.run_review(assessment_id="demo", requirement_id="R1", refresh=True)
    monkeypatch.setattr(pipeline, "check_manifest", lambda: pytest.fail("Historical render read live index"))
    historical_after = review_state.render_report("demo", historical=True, revision=first.revision)
    assert historical_after == historical_before
    assert path.read_bytes() == markdown_before
    current = workflow["store"].load()
    for key, snapshot in old_buffer.items():
        assert current.source_buffer[key].model_dump() == snapshot


def test_canonical_storage_rejects_removing_old_source_snapshots(workflow):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    before = workflow["store"].path.read_bytes()
    changed = state.model_copy(deep=True)
    changed.source_buffer.clear()
    with workflow["store"].locked(), pytest.raises(ValueError):
        workflow["store"].save(changed, changed.revision)
    assert workflow["store"].path.read_bytes() == before


def test_read_only_schema_v1_upgrade_never_invents_raw_provenance(workflow):
    state = pipeline.run_review(assessment_id="demo", limit=1)
    data = state.model_dump()
    data["schema_version"] = 1
    data.pop("source_buffer")
    for section in data["sections"].values():
        for key in ("applicability_result", "legal_anchor", "legal_anchor_issue", "retrieved_buffer_ids", "model_calls", "draft_call_id", "claim_links", "citation_issues"):
            section.pop(key)
        section["audit_status"] = "identifier_checked_only"
        for revision in section["finding_history"]:
            for key in ("legal_anchor", "legal_anchor_issue", "retrieved_buffer_ids", "draft_call_id", "claim_links", "citation_issues"):
                revision.pop(key)
    workflow["store"].path.write_text(json.dumps(data), encoding="utf-8")
    original = workflow["store"].path.read_bytes()
    loaded = workflow["store"].load()
    assert loaded.schema_version == 3
    assert not loaded.source_buffer
    assert not loaded.sections["R1"].claim_links
    assert loaded.sections["R1"].audit_status == "identifier_checked_only"
    assert workflow["store"].path.read_bytes() == original
    legacy_export = report_state.compatibility_report(loaded, historical=True)
    assert not legacy_export["findings"][0]["legal_quote_verified"]
    assert legacy_export["findings"][0]["requirement"]["exact_quote"] == ""


def test_reranker_and_drafter_have_distinct_saved_contexts(workflow, monkeypatch):
    import ollama

    records = [record(key=f"D-{n}", block=n, sha="device-hash",
                      text="Synthetic maintenance records" if n == 1 else f"Other text {n}") for n in range(1, 4)]

    class Collection:
        def get(self, **kwargs):
            return {"ids": [r["id"] for r in records], "documents": [r["text"] for r in records],
                    "metadatas": [r["meta"] for r in records]}

        def query(self, **kwargs):
            return {"ids": [[r["id"] for r in records]]}

    monkeypatch.setenv("RERANK_ENABLED", "true")
    monkeypatch.setattr(search, "collection", Collection)
    monkeypatch.setattr(search, "embeddings", lambda *args: [[1.0]])
    monkeypatch.setattr(pipeline, "hybrid_search", search.hybrid_search)
    monkeypatch.setattr(ollama, "chat", lambda **kwargs: {"message": {"content": json.dumps({"scores": [
        {"source_id": f"D-{n}", "score": 100 - n} for n in range(1, 4)]})}})
    state = pipeline.run_review(assessment_id="demo", limit=1, k=1)
    calls = state.sections["R1"].model_calls
    rerank = next(call for call in calls if call.stage == "rerank")
    draft = next(call for call in calls if call.stage == "review_draft")
    assert len(rerank.presented) == 3
    assert sum(state.source_buffer[item.buffer_id].kind == "device" for item in draft.presented) == 1
    assert all(call.outcome == "completed" for call in calls)
    assert len(state.sections["R1"].retrieved_buffer_ids) == 3


def test_retrieval_trace_includes_backend_union_before_fusion_cap(tmp_path, monkeypatch):
    records = [record(key=f"D-{n:02d}", block=n + 1,
                      text="targetkeyword evidence" if 12 <= n < 18 else "general unrelated background")
               for n in range(24)]

    class Collection:
        def get(self, **kwargs):
            return {"ids": [r["id"] for r in records], "documents": [r["text"] for r in records],
                    "metadatas": [r["meta"] for r in records]}

        def query(self, **kwargs):
            return {"ids": [[r["id"] for r in records[:12]]]}

    monkeypatch.setattr(search, "collection", Collection)
    monkeypatch.setattr(search, "embeddings", lambda *args: [[1.0]])
    run = EvidenceRun(tmp_path, "retrieval-test")
    with recording(run.recorder):
        results = search.hybrid_search("targetkeyword", "device", k=1, mode="hybrid", rerank=False)
    assert len(results) == 1
    assert len(run.recorder.retrieved) == 18  # Twelve dense + six positive BM25 candidates.


def test_extraction_captures_legal_snapshot_call_and_verified_raw_anchor(workflow, monkeypatch):
    raw = "The manufacturer shall maintain\n records for R1."
    normalized = "The manufacturer shall maintain records for R1."
    part = record(raw, key="L-1", kind="legal", source="legal/law.pdf", sha="law-hash", page=1)

    class FakePDF:
        def __len__(self):
            return 1

        def close(self):
            pass

    monkeypatch.setattr(pipeline, "extract_requirements", workflow["extract"])
    monkeypatch.setattr(pipeline, "DOCS", workflow["root"].parent / "documents")
    monkeypatch.setattr(pipeline, "choose_legal_source", lambda filename: "legal/law.pdf")
    monkeypatch.setattr(pipeline, "legal_chunks", lambda *args: [part])
    monkeypatch.setattr(pipeline.fitz, "open", lambda *args: FakePDF())
    monkeypatch.setattr(pipeline, "llm_parse", lambda *args: RequirementBatch(items=[RequirementCandidate(
        requirement="Retain the records", exact_quote=normalized, provision="Annex I", applies_to="manufacturer")]))
    pipeline.extract_requirements("1", "law.pdf")
    register = json.loads(workflow["draft_path"].read_text(encoding="utf-8"))
    req = register["requirements"][0]
    assert req["id"] == "R1"
    assert req["exact_quote"] == raw
    assert req["legal_quote_verified"]
    trace = json.loads((workflow["root"] / register["evidence_trace"]).read_text(encoding="utf-8"))
    assert trace["publication_status"] == "draft_register_only"
    assert len(trace["model_calls"]) == 1
    assert len(trace["links"]) == 1
    assert trace["links"][0]["exact_quote"] == raw
