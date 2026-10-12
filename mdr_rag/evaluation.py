"""Human-gold-label benchmark for dense, BM25, hybrid RRF, and optional reranking."""
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import plotly.express as px
from rank_bm25 import BM25Okapi

from .core import REPORTS, ROOT
from .pipeline import check_manifest
from .search import _tokens, collection, embeddings, rerank_passages, reranking_enabled


def load_gold(path):
    path = Path(path)
    examples = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(examples, list) or not examples:
        raise ValueError(f"Gold set {path} is empty. Annotate real queries and source pages first.")
    ids = set()
    for ex in examples:
        if not isinstance(ex, dict) or not isinstance(ex.get("query"), str) or not ex["query"].strip():
            raise ValueError("Gold rows must contain a nonempty 'query' string")
        if ex.get("kind") not in {"legal", "device"}:
            raise ValueError("Gold row kind must be 'legal' or 'device'")
        if not isinstance(ex.get("id"), str) or not ex["id"].strip() or ex["id"] in ids:
            raise ValueError("Gold IDs must be unique nonblank strings")
        ids.add(ex["id"])
        if not isinstance(ex.get("relevant"), list) or not ex["relevant"]:
            raise ValueError(f"{ex['id']}: at least one human-verified relevant source/page required")
        signatures = set()
        for label in ex["relevant"]:
            if not isinstance(label, dict) or not isinstance(label.get("source"), str):
                raise ValueError(f"{ex['id']}: a relevant label needs 'source'")
            if label.get("page") is not None and (type(label["page"]) is not int or label["page"] < 1):
                raise ValueError(f"{ex['id']}: page must be positive integer or null (whole document)")
            if label.get("chunk_id") is not None and not isinstance(label["chunk_id"], str):
                raise ValueError(f"{ex['id']}: chunk_id must be a string")
            signature = (label["source"], label.get("page"), label.get("chunk_id"))
            if signature in signatures:
                raise ValueError(f"{ex['id']}: duplicate gold label {signature}")
            signatures.add(signature)
    return examples


def relevant_label(meta, labels, chunk_id=None):
    """Return index of first human relevant source/page matching this retrieved chunk."""
    for i, label in enumerate(labels):
        if (meta["source"] == label["source"]
            and (label.get("page") is None or meta.get("page") == label["page"])
            and (label.get("chunk_id") is None or chunk_id == label["chunk_id"])):
            return i
    return None


def rank_scores(ranked_ids, meta_by_id, labels, k):
    """Binary relevance per distinct human-labeled source/page, avoiding duplicate chunks."""
    seen = set()
    relevant_positions = []
    for rank, chunk_id in enumerate(ranked_ids[:k], start=1):
        label_idx = relevant_label(meta_by_id[chunk_id], labels, chunk_id)
        if label_idx is not None and label_idx not in seen:
            seen.add(label_idx)
            relevant_positions.append(rank)
    total_gold = len(labels)
    dcg = sum(1 / math.log2(pos + 1) for pos in relevant_positions)
    ideal_dcg = sum(1 / math.log2(i + 1) for i in range(1, min(total_gold, k) + 1))
    return {
        "precision": len(seen) / k,
        "recall": len(seen) / total_gold,
        "hit_rate": 1.0 if seen else 0.0,
        "mrr": 1 / min(relevant_positions) if relevant_positions else 0.0,
        "ndcg": dcg / ideal_dcg if ideal_dcg else 0.0,
        "found_labels": sorted(seen),
        "unfound_labels": [i for i in range(total_gold) if i not in seen],
    }


def fusion(semantic_ids, bm25_ids, scores_by_id, take, rrf_k=60):
    """Same reciprocal-rank fusion rule as search.hybrid_search."""
    combined = {}
    for rank, key in enumerate(semantic_ids[:max(take * 3, 12)]):
        combined[key] = combined.get(key, 0.0) + 1 / (rrf_k + rank + 1)
    for rank, key in enumerate(bm25_ids[:max(take * 3, 12)]):
        if scores_by_id[key] <= 0:
            continue
        combined[key] = combined.get(key, 0.0) + 1 / (rrf_k + rank + 1)
    return sorted(combined, key=lambda key: combined[key], reverse=True)


def evaluate(gold_path=None, ks=(3, 5, 10), destination=None, include_reranked=None):
    manifest = check_manifest()
    file_path = Path(gold_path) if gold_path else ROOT / "eval" / "gold_queries.json"
    examples = load_gold(file_path)
    ks = sorted(set(int(k) for k in ks))
    if not ks or min(ks) < 1:
        raise ValueError("K values must be positive integers")
    top_k = max(ks)
    if include_reranked is None:
        include_reranked = reranking_enabled()
    db = collection()
    corpora = {}
    for kind in ("legal", "device"):
        data = db.get(where={"kind": kind}, include=["documents", "metadatas"])
        ids = data["ids"]
        docs = data["documents"] or []
        metadatas = data["metadatas"] or []
        corpora[kind] = {
            "ids": ids, "docs": docs, "metadata": metadatas,
            "metadata_by_id": dict(zip(ids, metadatas)),
            "bm25": BM25Okapi([_tokens(doc) for doc in docs]) if docs else None,
        }
    results = []
    for n, ex in enumerate(examples, 1):
        kind = ex["kind"]
        corpus = corpora[kind]
        ids = corpus["ids"]
        if not ids:
            raise ValueError(f"{ex['id']}: no indexed chunks of kind {kind!r}")
        indexed_locations = {(m["source"], m.get("page")) for m in corpus["metadata"]}
        indexed_sources = {m["source"] for m in corpus["metadata"]}
        # Invalid gold must STOP the benchmark; otherwise recall could be deceptive.
        for gold in ex["relevant"]:
            found = ((gold["source"], gold.get("page")) in indexed_locations
                     if gold.get("page") is not None else gold["source"] in indexed_sources)
            if found and gold.get("chunk_id") is not None:
                found = (gold["chunk_id"] in corpus["metadata_by_id"] and
                         corpus["metadata_by_id"][gold["chunk_id"]]["source"] == gold["source"] and
                         (gold.get("page") is None or
                          corpus["metadata_by_id"][gold["chunk_id"]].get("page") == gold["page"]))
            if not found:
                raise ValueError(f"{ex['id']}: ground-truth label not in index: {gold}")
        query_vector = embeddings([ex["query"]])[0]
        dense = db.query(query_embeddings=[query_vector], where={"kind": kind},
                         n_results=min(len(ids), max(top_k * 3, 12)), include=["distances"])["ids"][0]
        scores = corpus["bm25"].get_scores(_tokens(ex["query"]))
        lexical_order = sorted(range(len(ids)), key=lambda i: (-float(scores[i]), ids[i]))
        bm25 = [ids[i] for i in lexical_order]
        scores_by_id = {ids[i]: float(scores[i]) for i in range(len(ids))}
        hybrid = fusion(dense, bm25, scores_by_id, top_k)
        methods = [("dense", dense), ("bm25", bm25), ("hybrid", hybrid)]
        if include_reranked:
            candidate_count = min(max(top_k * 3, 12), len(hybrid))
            candidates = [
                {
                    "id": chunk_id,
                    "text": corpus["docs"][ids.index(chunk_id)],
                    "meta": corpus["metadata_by_id"][chunk_id],
                }
                for chunk_id in hybrid[:candidate_count]
            ]
            reranked = rerank_passages(ex["query"], candidates)
            methods.append(("hybrid_reranked", [passage["id"] for passage in reranked]))
        for method, ordered in methods:
            for k in ks:
                result = rank_scores(ordered, corpus["metadata_by_id"], ex["relevant"], k)
                matched = [ex["relevant"][i] for i in result.pop("found_labels")]
                missed = [ex["relevant"][i] for i in result.pop("unfound_labels")]
                results.append({
                    "query_id": ex["id"], "question": ex["query"], "kind": kind,
                    "method": method, "k": k, **result,
                    "found_labels": matched, "missed_labels": missed,
                    "retrieved": [
                        {"id": chunk, "source": corpus["metadata_by_id"][chunk]["source"],
                         "page": corpus["metadata_by_id"][chunk].get("page")}
                        for chunk in ordered[:k]
                    ],
                })
        print(f"Evaluated {n}/{len(examples)} questions", flush=True)
    methods = ["dense", "bm25", "hybrid"]
    if include_reranked:
        methods.append("hybrid_reranked")
    keys = ("precision", "recall", "hit_rate", "mrr", "ndcg")
    aggregate = []
    for method in methods:
        for k in ks:
            sub = [r for r in results if r["method"] == method and r["k"] == k]
            aggregate.append({"method": method, "k": k, "questions": len(sub),
                              **{m: round(sum(row[m] for row in sub) / len(sub), 5) for m in keys}})
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "gold_file": str(file_path),
        "n_questions": len(examples),
        "n_legal_questions": sum(ex["kind"] == "legal" for ex in examples),
        "n_device_questions": sum(ex["kind"] == "device" for ex in examples),
        "embedding_model": manifest["embedding_model"],
        "reranker_model": os.getenv("OLLAMA_LLM_MODEL", "qwen3:4b") if include_reranked else None,
        "reranker_candidate_count": max(top_k * 3, 12) if include_reranked else None,
        "indexed_sources_sha256": {item["source"]: item["sha256"] for item in manifest["files"]},
        "k_values": ks,
        "average_metrics": aggregate,
        "per_query": results,
        "interpretation": "Ground-truth retrieval benchmark only. Does not measure answer faithfulness, legal completeness, safety, or compliance. Gold labels need human validation.",
    }
    path = Path(destination) if destination else REPORTS / "retrieval_evaluation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    chart_data = []
    for row in aggregate:
        for metric in keys:
            chart_data.append({"retriever": row["method"], "k": row["k"],
                               "metric": metric.upper(), "score": row[metric]})
    fig = px.line(chart_data, x="k", y="score", color="retriever", facet_col="metric",
                  facet_col_wrap=3, markers=True, title="Retrieval benchmark: human-labeled questions",
                  category_orders={"metric": [m.upper() for m in keys]})
    fig.update_yaxes(range=[0, 1], matches=None)
    fig.update_layout(height=760)
    html_path = path.with_suffix(".html")
    fig.write_html(html_path, include_plotlyjs=True)
    print(f"Evaluation data: {path}\nEvaluation charts: {html_path}")
    for row in aggregate:
        if row["k"] == max(ks):
            print(f"  {row['method']:>6} k={row['k']}: Recall={row['recall']:.3f}, "
                  f"MRR={row['mrr']:.3f}, nDCG={row['ndcg']:.3f}")
    return report


def inspect_candidates(question, kind="legal", k=8):
    """Help annotators select true gold pages. Shows evidence, never auto-labels relevance."""
    from .search import hybrid_search
    check_manifest()
    passages = hybrid_search(question, kind, k)
    for i, p in enumerate(passages, 1):
        m = p["meta"]
        print(f"\n{i}. {p['id']}  {m['source']}  page={m['page']} block={m['block']}")
        print(re.sub(r"\s+", " ", p["text"])[:500])
