import json
from types import SimpleNamespace

import pytest

from mdr_rag import search, pipeline, review_state
from mdr_rag.query_planner import plan_queries, PlannerSelection
from test_report_state import workflow


@pytest.fixture
def corpus(monkeypatch):
    search._BM25_CACHE.clear()
    records = [{"id": f"D-{n:02}", "text": "rareartifact" if n == 1 else f"ordinary record {n}",
                "meta": {"kind": "device", "source": "device/records.txt", "sha256": "device-hash", "page": 0, "block": n + 1}}
               for n in range(40)]
    calls = {"get": 0, "dense": [], "embed": []}

    class Collection:
        def get(self, **kwargs):
            calls["get"] += 1
            assert kwargs["where"] == {"kind": "device"}
            return {"ids": [r["id"] for r in records], "documents": [r["text"] for r in records],
                    "metadatas": [r["meta"] for r in records]}

        def query(self, **kwargs):
            calls["dense"].append(kwargs)
            assert kwargs["where"] == {"kind": "device"}
            # Deliberately include repeated and out-of-scope IDs.
            return {"ids": [["L-wrong", "D-00", "D-00", "D-02", "invented"]]}

    monkeypatch.setattr(search, "collection", Collection)
    monkeypatch.setattr(search, "embeddings", lambda queries: calls["embed"].append(queries) or [[1.0]])
    return records, calls


def test_expansion_only_passage_and_provenance(corpus):
    result = search.retrieve_candidates(["ordinary", "rareartifact"], "device", mode="hybrid", rerank=False)
    assert "D-01" in result["trace"]["merged_ids"]
    candidate = next(c for c in result["trace"]["candidates"] if c["id"] == "D-01")
    assert any(p["query"] == "rareartifact" and p["backend"] == "bm25" for p in candidate["provenance"])
    assert all(c["provenance"] for c in result["trace"]["candidates"])
    assert all(p["query_rank"] > 0 and p["backend_rank"] > 0 for c in result["trace"]["candidates"] for p in c["provenance"])


def test_duplicate_queries_and_backend_ids_do_not_vote_twice(corpus):
    first = search.retrieve_candidates(["ordinary", "rareartifact"], "device", mode="hybrid", rerank=False)
    duplicate = search.retrieve_candidates(["ordinary", " ORDINARY ", "rareartifact", ""], "device", mode="hybrid", rerank=False)
    assert first["trace"]["candidates"] == duplicate["trace"]["candidates"]
    assert all(sum(p["query_id"] == "Q1" and p["backend"] == "dense" for p in c["provenance"]) <= 1 for c in first["trace"]["candidates"])


def test_filters_reject_unknown_and_wrong_kind(corpus):
    records, _ = corpus
    records[2]["meta"]["kind"] = "legal"
    records[0]["meta"]["source"] = "legal/wrong.pdf"
    result = search.retrieve_candidates(["ordinary"], "device", mode="dense", rerank=False)
    assert result["passages"] == []


def test_bm25_never_embeds_and_cache_uses_manifest(corpus, monkeypatch):
    _, calls = corpus
    builds = []
    original = search.BM25Okapi
    monkeypatch.setattr(search, "BM25Okapi", lambda tokens: builds.append(tokens) or original(tokens))
    for query in ("ordinary", "rareartifact"):
        search.retrieve_candidates([query], "device", mode="bm25", rerank=False, manifest_fingerprint="v1")
    assert calls["embed"] == calls["dense"] == []
    assert calls["get"] == len(builds) == 1
    search.retrieve_candidates(["ordinary"], "device", mode="bm25", rerank=False, manifest_fingerprint="v2")
    assert calls["get"] == len(builds) == 2


def test_bounds_and_stable_ties(corpus):
    result = search.retrieve_candidates(["a", "b", "c", "d"], "device", mode="dense", rerank=False, k=30)
    assert len(result["trace"]["merged_ids"]) <= 30
    assert all(call["n_results"] <= 12 for call in corpus[1]["dense"])
    assert result == search.retrieve_candidates(["a", "b", "c", "d"], "device", mode="dense", rerank=False, k=30)


@pytest.mark.parametrize("options", [{"per_backend": 13}, {"merged_limit": 31}, {"k": 31}, {"mode": "bad"}])
def test_invalid_budgets(corpus, options):
    with pytest.raises(ValueError):
        search.retrieve_candidates(["original"], "device", **options)


def test_merged_cap_with_disjoint_lists(corpus, monkeypatch):
    class Collection:
        def get(self, **kwargs):
            return {"ids": [r["id"] for r in corpus[0]], "documents": [r["text"] for r in corpus[0]], "metadatas": [r["meta"] for r in corpus[0]]}
        def query(self, **kwargs):
            start = kwargs["query_embeddings"][0][0]
            return {"ids": [[r["id"] for r in corpus[0][start:start+12]]]}
    monkeypatch.setattr(search, "collection", Collection)
    monkeypatch.setattr(search, "embeddings", lambda queries: [[int(queries[0])]])
    result = search.retrieve_candidates(["0", "12", "24", "36"], "device", mode="dense", rerank=False, k=30)
    assert len(result["trace"]["candidates"]) == 40
    assert len(result["trace"]["merged_ids"]) == len(result["passages"]) == 30
    # Equal query-level ranks tie on chunk ID, independent of input dict order.
    assert result["trace"]["merged_ids"][:4] == ["D-00", "D-12", "D-24", "D-36"]


def requirement():
    return SimpleNamespace(provision="Annex I", requirement="Maintain risk management records", exact_quote="Maintain risk management records.")


@pytest.mark.parametrize("failure", [lambda *args: (_ for _ in ()).throw(ValueError("bad JSON")),
                                     lambda *args: {"selected_ids": ["invented"]},
                                     lambda *args: {"unexpected": "other jurisdiction"}])
def test_planner_fallback(failure):
    deterministic = plan_queries(requirement())
    fallback = plan_queries(requirement(), llm=failure)
    assert fallback.queries == deterministic.queries
    assert fallback.fallback == "invalid_or_failed_llm_selection"


def test_planner_scope_and_original():
    plan = plan_queries(requirement(), {"device_name": "Named device", "classification": "ForbiddenClass", "jurisdiction": "ForbiddenMarket"})
    assert len(plan.queries) == 4
    assert plan.queries[0].text == "Annex I Maintain risk management records Maintain risk management records."
    assert "Named device" in plan.queries[-1].text
    assert "Forbidden" not in json.dumps(plan.model_dump())
    selected = plan_queries(requirement(), llm=lambda *args: PlannerSelection(selected_ids=["Q3", "Q3"]))
    assert len(selected.queries) == 2
    assert selected.queries[0].intent == "original"


def test_default_review_persists_plan_and_trace_and_resumes(workflow, corpus, monkeypatch):
    monkeypatch.delenv("MULTI_QUERY_ENABLED")
    # Keep fixture's valid cited chunk in the corpus.
    corpus[0][0]["id"] = "D-1"
    corpus[0][0]["text"] = "Synthetic maintenance records"
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    def interrupt(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(pipeline, "llm_parse", interrupt)
    with pytest.raises(KeyboardInterrupt):
        pipeline.run_review(assessment_id="demo", limit=1)
    saved = workflow["store"].load().sections["R1"]
    assert saved.checkpoint == "gate"
    assert len(saved.query_plan["queries"]) <= 4
    assert saved.retrieval_trace["candidates"]
    get_count = corpus[1]["get"]
    monkeypatch.setattr(pipeline, "llm_parse", workflow["llm"])
    final = pipeline.run_review(assessment_id="demo", resume=True, limit=1)
    assert corpus[1]["get"] == get_count
    assert final.sections["R1"].execution_status == "completed"
    assert final.sections["R1"].finding_history[-1]["retrieval_trace"] == saved.retrieval_trace


@pytest.mark.parametrize("name,value", [("MULTI_QUERY_MAX", "5"), ("RETRIEVAL_PER_QUERY", "13"),
                                        ("RETRIEVAL_MAX_CANDIDATES", "31"), ("QUERY_PLANNER", "bad"),
                                        ("MULTI_QUERY_ENABLED", "yes")])
def test_configuration_validation(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        review_state.configuration(7)


def test_planner_storage_error_is_not_a_fallback():
    from mdr_rag.query_planner import PlannerPersistenceError
    def fail(*args):
        raise PlannerPersistenceError("lock conflict")
    with pytest.raises(PlannerPersistenceError):
        plan_queries(requirement(), llm=fail)


def test_reranking_happens_once_on_bounded_pool(corpus, monkeypatch):
    calls = []
    monkeypatch.setattr(search, "rerank_passages", lambda query, records: calls.append((query, records)) or records)
    result = search.retrieve_candidates(["ordinary", "rareartifact"], "device", mode="hybrid", rerank=True)
    assert len(calls) == 1 and calls[0][0] == "ordinary"
    assert len(calls[0][1]) <= 30
    assert result["trace"]["reranked"]


def test_multi_query_targeted_update_preserves_other_sections(workflow, corpus, monkeypatch):
    monkeypatch.setenv("MULTI_QUERY_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    before = pipeline.run_review(assessment_id="demo")
    after = pipeline.run_review(assessment_id="demo", requirement_id="R2", refresh=True)
    for key in ("R1", "R3"):
        assert after.sections[key].model_dump() == before.sections[key].model_dump()
    assert after.sections["R2"].revision == before.sections["R2"].revision + 1
    assert len(workflow["calls"]["llm"]) == 0
    assert all(s.finding.status == "insufficient_evidence" for s in after.sections.values())


def test_review_invalid_planner_json_records_fallback_and_call(workflow, corpus, monkeypatch):
    monkeypatch.setenv("MULTI_QUERY_ENABLED", "true")
    monkeypatch.setenv("QUERY_PLANNER", "llm")
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    def parse(rules, prompt, schema):
        if schema is PlannerSelection:
            # Use the same validation path as malformed local-model JSON.
            return schema.model_validate_json('{broken')
        return workflow["llm"](rules, prompt, schema)
    monkeypatch.setattr(pipeline, "llm_parse", parse)
    section = pipeline.run_review(assessment_id="demo", limit=1).sections["R1"]
    assert section.query_plan["fallback"] == "invalid_or_failed_llm_selection"
    assert next(c for c in section.model_calls if c.stage == "query_planner").outcome == "failed"
    assert section.queries[0].startswith("Annex I")


def test_changed_planning_budget_invalidates_only_affected_stages(workflow):
    before = pipeline.run_review(assessment_id="demo")
    config = dict(before.config, multi_query_max=2)
    section = before.sections["R1"].model_copy(deep=True)
    updated = review_state.dependencies(section.requirement, before.device_profile, before.corpus_fingerprint, config)
    from mdr_rag.report_state import invalidate
    assert invalidate(section, updated)
    assert section.checkpoint == "applicability"
    assert section.query_plan is None and section.retrieval_trace is None


def test_legal_filter_is_enforced_locally_and_at_backend(monkeypatch):
    class Collection:
        def get(self, **kwargs):
            assert kwargs["where"] == {"kind": "legal"}
            return {"ids": ["L-1", "D-1"], "documents": ["Legal rule", "Device passage"],
                    "metadatas": [{"kind": "legal", "source": "legal/law.pdf"},
                                  {"kind": "device", "source": "device/file.txt"}]}
        def query(self, **kwargs):
            assert kwargs["where"] == {"kind": "legal"}
            return {"ids": [["D-1", "L-1"]]}
    monkeypatch.setattr(search, "collection", Collection)
    monkeypatch.setattr(search, "embeddings", lambda queries: [[1.0]])
    result = search.retrieve_candidates(["Legal rule"], "legal", mode="dense", rerank=False)
    assert [p["id"] for p in result["passages"]] == ["L-1"]


def test_cached_records_are_not_mutated_by_consumers(corpus):
    first = search.retrieve_candidates(["rareartifact"], "device", mode="bm25", rerank=False, manifest_fingerprint="immutable")
    first["passages"][0]["meta"]["source"] = "legal/wrong.pdf"
    second = search.retrieve_candidates(["rareartifact"], "device", mode="bm25", rerank=False, manifest_fingerprint="immutable")
    assert second["passages"][0]["meta"]["source"] == "device/records.txt"
