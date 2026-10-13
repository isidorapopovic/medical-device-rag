"""Gold validation and metric helpers over production evaluation experiments."""
import json
import math
import re
from pathlib import Path


from .core import ROOT
from .pipeline import check_manifest


def load_gold(path):
    path = Path(path)
    examples = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(examples, dict):
        examples = examples.get("cases")
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
        answerable = ex.get("answerable", True)
        if type(answerable) is not bool:
            raise ValueError(f"{ex['id']}: answerable must be an explicit JSON boolean")
        if not isinstance(ex.get("relevant"), list):
            raise ValueError(f"{ex['id']}: relevant must be an explicit list")
        if not answerable and ex["relevant"]:
            raise ValueError(f"{ex['id']}: unanswerable cases must have relevant=[]")
        if answerable and not ex["relevant"]:
            raise ValueError(f"{ex['id']}: at least one human-verified relevant source/page required")
        signatures = set()
        for label in ex["relevant"]:
            if not isinstance(label, dict) or not isinstance(label.get("source"), str):
                raise ValueError(f"{ex['id']}: a relevant label needs 'source'")
            if not label["source"].startswith(ex["kind"] + "/"):
                raise ValueError(f"{ex['id']}: label corpus differs from question kind")
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
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    total_gold = len(labels)
    dcg = sum(1 / math.log2(pos + 1) for pos in relevant_positions)
    ideal_dcg = sum(1 / math.log2(i + 1) for i in range(1, min(total_gold, k) + 1))
    return {
        "precision": len(seen) / k,
        "recall": len(seen) / total_gold if total_gold else None,
        "hit_rate": (1.0 if seen else 0.0) if total_gold else None,
        "mrr": (1 / min(relevant_positions) if relevant_positions else 0.0) if total_gold else None,
        "ndcg": (dcg / ideal_dcg if ideal_dcg else 0.0) if total_gold else None,
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


def evaluate(gold_path=None, ks=(3, 5, 10), destination=None, include_reranked=None,
             *, methods=None, compare_all=False, run_id=None):
    """Compatibility entry point; all experiments use production candidates."""
    from .experiments import evaluate_production
    return evaluate_production(gold_path, ks, destination, include_reranked,
                               methods=methods, compare_all=compare_all, run_id=run_id)


def inspect_candidates(question, kind="legal", k=8):
    """Help annotators select true gold pages. Shows evidence, never auto-labels relevance."""
    from .search import hybrid_search
    check_manifest()
    passages = hybrid_search(question, kind, k)
    for i, p in enumerate(passages, 1):
        m = p["meta"]
        print(f"\n{i}. {p['id']}  {m['source']}  page={m['page']} block={m['block']}")
        print(re.sub(r"\s+", " ", p["text"])[:500])
