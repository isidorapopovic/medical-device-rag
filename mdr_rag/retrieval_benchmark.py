"""Synthetic retrieval regression only: no regulatory law or expert judgments."""
import argparse
import hashlib
import json
import math
import time
import statistics
from pathlib import Path

from . import search

# Frozen before Stage 06 changes. Toy expected IDs follow literal fixture terms,
# not LLM labels or regulatory expert judgments. Keep every case, including misses.
def fixture():
    texts = [
        ("clause", "SYNTHETIC clause Z9.4 cobalt fatigue record"),
        ("abbr", "SYNTHETIC electromagnetic compatibility EMC immunity protocol"),
        ("unicode", "SYNTHETIC sterilizacija stérilisation Überprüfung zapis"),
        ("negative", "SYNTHETIC valve is not sterile packaging exclusion record"),
        ("table", "SYNTHETIC test | pressure | 42 | result | recorded"),
        ("stuff", "SYNTHETIC " + "cobalt " * 100),
    ]
    texts += [(f"noise{i}", f"SYNTHETIC unrelated inventory item warehouse {i}") for i in range(1010)]
    records = [{"id": key, "text": text, "meta": {"kind": "device", "source": "device/toy.txt",
                "sha256": "synthetic", "block": i, "page": 0}} for i, (key, text) in enumerate(texts)]
    cases = [
        {"id": "exact", "slice": "clause", "query": "Z9.4 fatigue", "relevant": ["clause"]},
        {"id": "abbreviation", "slice": "abbreviation", "query": "EMC immunity", "relevant": ["abbr"]},
        {"id": "unicode", "slice": "multilingual", "query": "stérilisation Überprüfung", "relevant": ["unicode"]},
        {"id": "negation", "slice": "negation", "query": "not sterile packaging", "relevant": ["negative"]},
        {"id": "table", "slice": "table", "query": "pressure recorded", "relevant": ["table"]},
        {"id": "stuffing", "slice": "adversarial", "query": "cobalt fatigue record", "relevant": ["clause"]},
        {"id": "no-match", "slice": "unanswerable", "query": "xylophone quantumbanana", "relevant": []},
    ]
    return records, cases


class Rows:
    """Offline collection seam; deliberately has no dense query method."""
    def __init__(self, records):
        self.records = records
        self.id = "synthetic-regression"
    def get(self, **kwargs):
        records = [r for r in self.records if r["meta"]["kind"] == kwargs["where"]["kind"]]
        return {"ids": [r["id"] for r in records], "documents": [r["text"] for r in records],
                "metadatas": [r["meta"] for r in records]}


def metrics(ranked, relevant, k):
    selected = list(dict.fromkeys(ranked))[:k]
    hits = [i for i, key in enumerate(selected, 1) if key in relevant]
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
    return {"recall": len(hits) / len(relevant) if relevant else None,
            "mrr": 1 / hits[0] if hits else (0.0 if relevant else None),
            "ndcg": sum(1 / math.log2(i + 1) for i in hits) / ideal if ideal else None}


def measure(retrieve, cases):
    results = []
    for case in cases:
        started = time.perf_counter()
        ids = retrieve(case["query"])
        results.append({"case_id": case["id"], "slice": case["slice"], "ids": ids,
            "milliseconds": (time.perf_counter() - started) * 1000,
            "zero_match": not ids, **{f"at{k}": metrics(ids, case["relevant"], k) for k in (5, 10)}})
    def aggregate(rows):
        return {**{f"{metric}@{k}": sum(v) / len(v) if v else None
                   for k in (5, 10) for metric in ("recall", "mrr", "ndcg")
                   for v in [[row[f"at{k}"][metric] for row in rows if row[f"at{k}"][metric] is not None]]},
                "latency_mean_ms": sum(r["milliseconds"] for r in rows) / len(rows),
                "latency_median_ms": statistics.median(r["milliseconds"] for r in rows),
                "latency_p95_ms": sorted(r["milliseconds"] for r in rows)[max(0, math.ceil(.95*len(rows))-1)],
                "zero_match_rate": sum(r["zero_match"] for r in rows) / len(rows)}
    return {"cases": results, "overall": aggregate(results),
            "slices": {name: aggregate([r for r in results if r["slice"] == name]) for name in sorted({r["slice"] for r in results})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    records, cases = fixture()
    rows = Rows(records)
    result = measure(lambda q: [r["id"] for r in search.retrieve_candidates(
        [q], "device", mode="bm25", rerank=False, k=10, corpus_override=rows)["passages"]], cases)
    from .structural_retrieval import structural_ranges
    from .query_expansion import expand_query
    children, parent_of = [], {}
    for parent in records:
        for left, right in structural_ranges(parent["text"]):
            child = {"id": f"{parent['id']}:{left}:{right}", "text": parent["text"][left:right],
                     "meta": dict(parent["meta"])}
            children.append(child)
            parent_of[child["id"]] = parent["id"]
    def structural(q, expand=False):
        queries = [p.text for p in expand_query(q, scope="frozen-synthetic-fixture").queries] if expand else [q]
        found = search.retrieve_candidates(queries, "device", mode="bm25", rerank=False, k=10,
                                          corpus_override=Rows(children), resilient=True)["passages"]
        return list(dict.fromkeys(parent_of[p["id"]] for p in found))
    structural_result = measure(structural, cases)
    expansion_result = measure(lambda q: structural(q, expand=True), cases)
    report = {"structural_bm25": structural_result, "expanded_structural_bm25": expansion_result,
        "synthetic_demonstration_only": True, "expert_validated": False,
        "fixture_sha256": hashlib.sha256(json.dumps([records, cases], sort_keys=True).encode()).hexdigest(),
        "chunks": len(records), "bm25": result, "dense": "NOT RUN: no installed-model benchmark",
        "hybrid": "NOT RUN: no installed-model benchmark", "llm_rerank": "NOT RUN",
        "cross_encoder": "NOT RUN", "cloud_calls": 0, "default_promotion": False}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
