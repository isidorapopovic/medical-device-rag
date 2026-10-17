"""Stage 06 synthetic non-regulatory illustrations; no law or expert labels."""
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from mdr_rag import search
from mdr_rag.errors import Cancelled, MissingModel, BudgetExceeded, ParsingError
from mdr_rag.ingestion import IngestionStore
from mdr_rag.query_expansion import expand_query, CACHE
from mdr_rag.retrieval_benchmark import fixture, Rows, measure, metrics
from mdr_rag.retrieval_safety import RecordCollection
from mdr_rag.structural_retrieval import StructuralIndex, structural_ranges
from mdr_rag.reranking import RerankerUnavailable


@pytest.fixture
def structural(tmp_path):
    store = IngestionStore(tmp_path / "ingestion", "synthetic-project")
    content = ("# SYNTHETIC DEVICE, NON-REGULATORY\n\n"
        "1. EMC electromagnetic compatibility immunity protocol.\n"
        "2. This fictional valve is not sterile.\n\n"
        "| test | pressure | recorded |\n| toy | 42 | yes |\n").encode()
    manifest, key = store.ingest("device", "toy.md", content)
    index = StructuralIndex(tmp_path / "retrieval", store)
    snapshot = index.build([key], "device", target=100)
    docs = tmp_path / "documents"
    (docs / "device").mkdir(parents=True)
    (docs / "device" / "toy.md").write_bytes(content)
    return store, index, snapshot, key, manifest, docs


def test_canonical_parent_citations_and_exact_children(structural, monkeypatch):
    store, index, key, _, manifest, docs = structural
    monkeypatch.setattr(search, "embeddings", lambda _: pytest.fail("BM25 must be offline"))
    result = index.retrieve(key, ["EMC immunity"], documents_root=docs)
    assert result["passages"]
    for parent in result["passages"]:
        span = next(s for s in manifest.spans if s.id == parent["meta"]["source_span_id"])
        assert parent["text"] == span.text
        assert parent["meta"]["document_version"] == 1
        store.view(parent["meta"]["manifest_sha256"], span.id)
    snapshot = index.load(key)
    assert all(c["text"] == next(p for p in snapshot.parents if p["id"] == c["meta"]["parent_id"])["text"][
        c["meta"]["child_start"]:c["meta"]["child_end"]] for c in snapshot.children)
    assert result["structural"]["child_to_parent"]
    assert result["diagnostics"]["status"] == "candidates_require_verification"


def test_structural_atomic_table_clause_and_long_prose():
    text = "1. First toy clause.\n2. Second toy clause.\n\n| table | row |\n| a | b |"
    ranges = structural_ranges(text, 100)
    assert any(text[a:b].startswith("1.") and "2." not in text[a:b] for a, b in ranges)
    assert any("| table | row |\n| a | b |" in text[a:b] for a, b in ranges)
    assert structural_ranges("word " * 300, 100) == [(0, 1499)]
    assert structural_ranges("") == []


@pytest.mark.parametrize("text,target", [("x"*20001,800), ("text",0), ("text",5000)])
def test_structural_bounds(text, target):
    with pytest.raises(ValueError):
        structural_ranges(text,target)


def test_no_relevant_evidence_is_abstention(structural):
    _, index, key, *_ = structural
    result = index.retrieve(key, ["xylophonequantum"])
    assert result["passages"] == []
    assert result["diagnostics"]["status"] == "no_relevant_evidence"
    assert result["structural"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("change", ["changed", "deleted"])
def test_current_sources_fail_closed(structural, change):
    _, index, key, _, _, docs = structural
    path = docs / "device" / "toy.md"
    path.write_text("SYNTHETIC changed") if change == "changed" else path.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        index.retrieve(key, ["EMC"], documents_root=docs)
    # Historical immutable snapshot remains explicitly usable via API.
    assert index.retrieve(key, ["EMC"])["passages"]


def test_index_identity_versions_and_duplicates(structural, monkeypatch):
    store, index, key, manifest_key, *_ = structural
    assert index.build([manifest_key], "device", target=100) == key
    with pytest.raises(ValueError):
        index.build([manifest_key, manifest_key], "device")
    revised, next_manifest = store.ingest("device", "toy.md", b"SYNTHETIC changed EMC record")
    assert revised.document.version == 2
    with pytest.raises(ValueError, match="duplicate document"):
        index.build([manifest_key,next_manifest], "device")
    assert index.build([next_manifest], "device") != key
    monkeypatch.setenv("EMBEDDING_REVISION", "synthetic-weights-v2")
    assert index.build([manifest_key], "device", target=100) != key
    result = index.retrieve(key, ["EMC"], mode="hybrid")
    assert "embedding_identity_mismatch" in result["diagnostics"]["fallback_codes"]


def test_wrong_project_kind_and_tampering(structural, tmp_path):
    store,index,key,mkey,*_ = structural
    with pytest.raises(ValueError):
        index.build([mkey],"legal")
    foreign = StructuralIndex(tmp_path / "retrieval",IngestionStore(store.root,"foreign"))
    with pytest.raises(FileNotFoundError):
        foreign.load(key)
    path=index._path(key)
    data=json.loads(path.read_text())
    data["children"][0]["text"]="SYNTHETIC forged"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match="hash"):
        index.load(key)


def test_archive_original_tamper_is_not_fallback(structural):
    store,index,key,mkey,manifest,_ = structural
    original=store.original(manifest)
    original.write_bytes(b"SYNTHETIC forged original")
    with pytest.raises(ValueError):
        index.retrieve(key,["EMC"],mode="hybrid")


def test_missing_dense_index_falls_back_without_creating_db(structural):
    _,index,key,*_=structural
    result=index.retrieve(key,["EMC"],mode="hybrid")
    assert result["passages"]
    assert "dense_index_unavailable" in result["diagnostics"]["fallback_codes"]
    assert not (index.directory/"vectors").exists()


@pytest.mark.parametrize("failure",[TimeoutError(),MissingModel(),BudgetExceeded(),ConnectionError()])
def test_dense_failure_lexical_fallback(failure,monkeypatch):
    rows,cases=fixture()
    monkeypatch.setattr(search,"embeddings",lambda _: (_ for _ in ()).throw(failure))
    result=search.retrieve_candidates(["EMC immunity"],"device",mode="hybrid",
        corpus_override=Rows(rows),resilient=True,diagnostics=True,rerank=False)
    assert result["passages"][0]["id"]=="abbr"
    assert result["diagnostics"]["fallback_codes"]==["dense_unavailable_lexical_fallback"]


@pytest.mark.parametrize("failure",[TimeoutError(),MissingModel(),RerankerUnavailable("synthetic")])
def test_reranker_failure_preserves_fusion(failure,monkeypatch):
    rows,_=fixture()
    monkeypatch.setattr(search,"rerank_passages",lambda *a,**kw: (_ for _ in ()).throw(failure))
    kwargs=dict(mode="bm25",corpus_override=Rows(rows),resilient=True,diagnostics=True)
    expected=search.retrieve_candidates(["cobalt record"],"device",rerank=False,**kwargs)["passages"]
    result=search.retrieve_candidates(["cobalt record"],"device",backend="llm",**kwargs)
    assert result["passages"]==expected
    assert result["trace"]["reranked"] is False
    assert "reranker_unavailable_fusion_preserved" in result["diagnostics"]["fallback_codes"]


@pytest.mark.parametrize("failure",[Cancelled(),ParsingError(),ValueError("schema"),RuntimeError("unknown ID")])
def test_invalid_evidence_or_cancellation_not_hidden(failure,monkeypatch):
    rows,_=fixture()
    monkeypatch.setattr(search,"rerank_passages",lambda *a,**kw: (_ for _ in ()).throw(failure))
    with pytest.raises(type(failure)):
        search.retrieve_candidates(["cobalt record"],"device",mode="bm25",backend="llm",
            corpus_override=Rows(rows),resilient=True)


def test_corrupt_chroma_requires_verified_snapshot(monkeypatch):
    rows,_=fixture()
    monkeypatch.setattr(search,"collection",lambda: (_ for _ in ()).throw(sqlite3.DatabaseError("PRIVATE")))
    with pytest.raises(sqlite3.DatabaseError):
        search.retrieve_candidates(["EMC"],"device",resilient=True)
    result=search.retrieve_candidates(["EMC"],"device",mode="hybrid",rerank=False,
        resilient=True,expected_records=rows,diagnostics=True)
    assert result["passages"][0]["id"]=="abbr"
    assert result["diagnostics"]["fallback_codes"]==["index_unavailable_lexical_snapshot"]


def test_stale_wrong_source_and_duplicate_protection():
    rows,_=fixture()
    rows=rows[:6]
    copied=copy.deepcopy(rows)
    copied[0]["meta"]["sha256"]="changed"
    with pytest.raises(ValueError,match="provenance"):
        search.retrieve_candidates(["cobalt"],"device",mode="bm25",rerank=False,
            corpus_override=Rows(copied),expected_records=rows,resilient=True)
    duplicate=copy.deepcopy(rows[0])
    duplicate["id"]="duplicate"
    contaminated=copy.deepcopy(rows[0])
    contaminated["id"]="legal-injection"
    contaminated["meta"]["kind"]="legal"
    result=search.retrieve_candidates(["cobalt"],"device",mode="bm25",rerank=False,
        corpus_override=Rows(rows+[duplicate,contaminated]),resilient=True,diagnostics=True)
    ids=[p["id"] for p in result["passages"]]
    assert not ("clause" in ids and "duplicate" in ids)
    assert "legal-injection" not in ids


@pytest.mark.parametrize("queries", [[],[""],["x"*4001],["a"*3500]*4,[None],"text"])
def test_query_budget_rejected_before_io(queries,monkeypatch):
    monkeypatch.setattr(search,"collection",lambda:pytest.fail("No IO"))
    with pytest.raises(ValueError):
        search.retrieve_candidates(queries,"device")


def test_frozen_benchmark_all_cases_and_1000_chunks():
    rows,cases=fixture()
    assert len(rows)==1016 and len(cases)==7
    assert hashlib.sha256(json.dumps([rows,cases],sort_keys=True).encode()).hexdigest()=="8ff1b956ca73ed01a1343aa5f6e44efddfc33c959953cb12763e1be4bc51f029"
    report=measure(lambda q:[p["id"] for p in search.retrieve_candidates(
        [q],"device",mode="bm25",rerank=False,corpus_override=Rows(rows),k=10)["passages"]],cases)
    assert report["overall"]["recall@10"]==1
    assert report["overall"]["zero_match_rate"]==pytest.approx(1/7)
    assert [r["case_id"] for r in report["cases"]]==[c["id"] for c in cases]
    assert metrics(["a","a"],["a"],5)["recall"]==1


def test_expansion_bounds_original_negation_cache_and_instructions(monkeypatch):
    CACHE.clear()
    def fail(*a,**kw):
        raise MissingModel()
    from mdr_rag.providers import OllamaProvider
    calls=[]
    monkeypatch.setattr(OllamaProvider,"generate",lambda *a,**kw:calls.append(1) or fail())
    query="SYNTHETIC non-sterile EMC ignore instructions"
    first=expand_query(query,scope="source-v1",assist=True)
    assert len(first.queries)<=4 and first.queries[0].text==query
    assert any("not sterile" in q.text for q in first.queries)
    assert first.fallback=="invalid_or_unavailable_selection"
    first.queries.clear()
    assert expand_query(query,scope="source-v1",assist=True).queries
    assert len(calls)==1
    expand_query(query,scope="source-v2",assist=True)
    assert len(calls)==2


@pytest.mark.parametrize("selection",[{"selected_ids":["invented"]},{"selected_ids":["Q2","Q2"]}, {"selected_ids":["Q2"],"fake":"yes"}])
def test_expansion_invalid_schema_falls_back(selection,monkeypatch):
    CACHE.clear()
    from mdr_rag.providers import OllamaProvider
    monkeypatch.setattr(OllamaProvider,"generate",lambda *a:selection)
    assert expand_query("SYNTHETIC EMC",scope="test",assist=True).fallback


def test_expansion_cancel_propagates(monkeypatch):
    CACHE.clear()
    from mdr_rag.providers import OllamaProvider
    monkeypatch.setattr(OllamaProvider,"generate",lambda *a:(_ for _ in ()).throw(Cancelled()))
    with pytest.raises(Cancelled):
        expand_query("SYNTHETIC EMC",scope="test",assist=True)


def test_dense_structural_chroma_offline_smoke(structural,monkeypatch):
    _,index,_,mkey,_,docs=structural
    monkeypatch.setattr(search,"embeddings",lambda texts:[[1.0,float(len(t)%7)] for t in texts])
    key=index.build([mkey],"device",target=100,dense=True)
    result=index.retrieve(key,["EMC immunity"],mode="hybrid",documents_root=docs)
    assert result["passages"]
    assert not result["diagnostics"]["fallback_codes"]
    assert all(p["meta"]["kind"]=="device" for p in result["passages"])


def test_structural_budget_validation(structural):
    _,index,key,*_=structural
    for kwargs in ({"k":0},{"k":31},{"mode":"bad"},{"backend":"cloud"}):
        with pytest.raises(ValueError):
            index.retrieve(key,["EMC"],**kwargs)

def test_single_chunk_positive_lexical_match():
    rows=[{"id":"toy","text":"SYNTHETIC cobalt fatigue","meta":{"kind":"device","source":"device/toy.txt"}}]
    result=search.retrieve_candidates(["cobalt"],"device",mode="bm25",rerank=False,
        corpus_override=Rows(rows),resilient=True)
    assert result["passages"][0]["id"]=="toy"


def test_missing_child_inventory_is_corruption(structural):
    _,index,key,*_=structural
    children=index.load(key).children
    with pytest.raises(ValueError,match="inventory"):
        search.retrieve_candidates(["EMC"],"device",mode="bm25",rerank=False,
            corpus_override=Rows(children[:-1]),expected_records=children,resilient=True)


def test_no_unrelated_query_expansion_or_model_call(monkeypatch):
    CACHE.clear()
    from mdr_rag.providers import OllamaProvider
    monkeypatch.setattr(OllamaProvider,"generate",lambda *a:pytest.fail("No selectable aliases"))
    plan=expand_query("xylophone quantumbanana",scope="toy",assist=True)
    assert len(plan.queries)==1


def test_logs_are_fixed_codes_and_hashed_projects(structural,caplog):
    import logging
    _,index,key,*_=structural
    caplog.set_level(logging.INFO,logger="mdr_rag.telemetry")
    index.retrieve(key,["EMC PRIVATE-QUERY-MARKER"])
    payload="\n".join(r.message for r in caplog.records)
    assert "PRIVATE-QUERY-MARKER" not in payload and "synthetic-project" not in payload
    events=[json.loads(r.message) for r in caplog.records if r.name=="mdr_rag.telemetry"]
    assert events and events[-1]["stage"]=="retrieval"
    assert events[-1]["outcome"]=="completed"


def test_recording_only_retains_canonical_parents(structural,tmp_path):
    from mdr_rag.source_buffer import EvidenceRun,recording
    _,index,key,*_=structural
    run=EvidenceRun(tmp_path/"state","synthetic-retrieval")
    with recording(run.recorder):
        result=index.retrieve(key,["EMC"])
    assert run.recorder.retrieved
    snapshots=[run.buffer.get_passage(i) for i in run.recorder.retrieved]
    assert all(not p.chunk_id.startswith("CH-") for p in snapshots)
    assert {p.chunk_id for p in snapshots}=={p["id"] for p in result["passages"]}


def test_snapshot_publish_failure_preserves_prior(structural,monkeypatch):
    import mdr_rag.structural_retrieval as module
    store,index,key,mkey,*_=structural
    before=index._path(key).read_bytes()
    def fail(*a,**kw):
        raise OSError("SYNTHETIC interrupted publication")
    monkeypatch.setattr(module,"atomic_bytes",fail)
    with pytest.raises(OSError):
        index.build([mkey],"device",target=200)
    assert index._path(key).read_bytes()==before
    assert index.load(key)


def test_revision_prevents_legacy_embedding_cache_reuse(tmp_path,monkeypatch):
    from mdr_rag import core
    from test_ingestion import FakeDatabase
    monkeypatch.setattr(core,"DOCS",tmp_path/"documents")
    (core.DOCS/"device").mkdir(parents=True)
    (core.DOCS/"device"/"toy.txt").write_text("SYNTHETIC device EMC record")
    db=FakeDatabase()
    monkeypatch.setattr(search,"open_db",lambda:db)
    calls=[]
    monkeypatch.setattr(search,"embeddings",lambda texts:calls.append(texts) or [[1.0] for t in texts])
    monkeypatch.setenv("EMBEDDING_REVISION","one")
    search.rebuild_index()
    search.rebuild_index()
    assert len(calls)==1
    monkeypatch.setenv("EMBEDDING_REVISION","two")
    search.rebuild_index()
    assert len(calls)==2


def test_saved_revision_and_dependency_binding(monkeypatch):
    from mdr_rag.saved_configuration import environment
    from mdr_rag.review_state import configuration,corpus_hash
    from mdr_rag.evidence_gate import gate_context
    assert environment({"embedding_model":"toy","embedding_revision":"weights-two"})["EMBEDDING_REVISION"]=="weights-two"
    assert environment({"embedding_model":"toy"})["EMBEDDING_REVISION"]==""
    monkeypatch.setenv("RERANK_BACKEND","none")
    monkeypatch.setenv("EMBEDDING_REVISION","two")
    config=configuration(7)
    assert config["embedding_revision"]=="two"
    context=gate_context(config,"toy-corpus",{})
    assert context.retrieval_configuration["embedding_revision"]=="two"
    first={"files":[],"embedding_model":"toy","embedding_revision":"one"}
    assert corpus_hash(first)!=corpus_hash({**first,"embedding_revision":"two"})


@pytest.mark.parametrize("query",["", "x"*3501])
def test_expansion_char_budgets(query):
    with pytest.raises(ValueError):
        expand_query(query,scope="toy")


def test_windows_filename_and_cli_offline(structural,monkeypatch,capsys):
    import main
    import sys
    import mdr_rag.retrieval_cli as cli
    store,index,key,mkey,_,docs=structural
    # Windows upload labels are normalized by existing ingestion.
    document,_=store.ingest("device",r"C:\uploads\synthetic.txt",b"SYNTHETIC Windows upload")
    assert document.document.original_name=="synthetic.txt"
    monkeypatch.setattr(cli,"STATE",index.root.parent)
    # CLI state layout is tested by explicit in-memory constructor seam.
    monkeypatch.setattr(cli,"IngestionStore",lambda *a,**kw:store)
    monkeypatch.setattr(cli,"StructuralIndex",lambda *a,**kw:index)
    monkeypatch.setattr(sys,"argv",["main.py","retrieve","EMC","--snapshot",key,
                                 "--documents-root",str(docs),"--expand"])
    assert main.main()==0
    result=json.loads(capsys.readouterr().out)
    assert result["passages"] and result["query_plan"]["queries"][0]["text"]=="EMC"

def test_programmatic_dense_build_shares_budget_across_batches(tmp_path,monkeypatch):
    import mdr_rag.runtime as runtime
    from mdr_rag.settings import Settings
    store=IngestionStore(tmp_path/"ingestion","synthetic-budget")
    content="\n".join(f"{i}. SYNTHETIC clause EMC immunity record number {i}." for i in range(1,81))
    _,manifest=store.ingest("device","budget.txt",content.encode())
    index=StructuralIndex(tmp_path/"retrieval",store)
    monkeypatch.setattr(runtime,"load_settings",lambda:Settings(root=tmp_path,max_llm_calls_per_run=1))
    calls,run_ids=[],[]
    def embed(texts):
        with runtime.provider_scope() as run:
            run_ids.append(run.id)
            def operation(timeout):
                calls.append(1)
                return {"vectors":[[1.0] for _ in texts],"prompt_eval_count":0,"eval_count":0}
            return run.call("embedding",operation,input_tokens=0,output_tokens=0,
                            prompt_chars=0,source_counts=len(texts))["vectors"]
    monkeypatch.setattr(search,"embeddings",embed)
    with pytest.raises(BudgetExceeded):
        index.build([manifest],"device",target=100,dense=True)
    assert len(calls)==1 and len(set(run_ids))==1
    assert not (index.directory/"vectors").exists()
    assert not list(index.directory.glob("*.json")) if index.directory.exists() else True
