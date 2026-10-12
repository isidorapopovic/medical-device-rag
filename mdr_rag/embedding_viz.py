"""Interactive PCA embedding explorer with embedding integrity and cosine diagnostics."""
import json
from collections import Counter
from pathlib import Path

import numpy as np
import plotly.express as px
from sklearn.decomposition import PCA

from .core import REPORTS
from .pipeline import check_manifest
from .search import collection, embeddings


def unit_vectors(vectors):
    x = np.asarray(vectors, dtype=np.float64)
    if x.ndim != 2 or x.shape[0] == 0:
        raise ValueError("Expected a nonempty 2D vector array")
    if not np.isfinite(x).all():
        raise ValueError("Embedding contains NaN or infinity")
    norms = np.linalg.norm(x, axis=1)
    if np.any(norms < 1e-12):
        raise ValueError("Embedding contains zero-length vectors")
    return x / norms[:, None]


def embedding_statistics(vectors, ids, metas, duplicate_threshold=0.98):
    x = unit_vectors(vectors)
    pairs = []
    # Keep duplicate checks bounded for large corpora; deterministic order.
    subset = x[:min(len(x), 350)]
    cos = subset @ subset.T
    for i in range(len(subset)):
        for j in range(i + 1, len(subset)):
            if cos[i, j] >= duplicate_threshold:
                pairs.append({"chunk_a": ids[i], "chunk_b": ids[j],
                              "cosine_similarity": round(float(cos[i, j]), 5)})
    pairs.sort(key=lambda r: r["cosine_similarity"], reverse=True)
    return {
        "n_embeddings": int(x.shape[0]),
        "dimension": int(x.shape[1]),
        "corpus_counts": dict(Counter(meta.get("kind", "unknown") for meta in metas)),
        "near_duplicate_threshold": duplicate_threshold,
        "near_duplicate_scan_first_n": len(subset),
        "near_duplicate_pairs_found_in_scan": len(pairs),
        "top_near_duplicate_pairs": pairs[:30],
        "warning": "Cosine and 2D proximity are not evidence of regulatory conformity."
    }


def visualize_embeddings(sample=600, query=None, destination=None):
    check_manifest()
    if sample < 3:
        raise ValueError("--sample must be at least 3")
    col = collection()
    data = col.get(include=["embeddings", "documents", "metadatas"])
    ids_all = data["ids"]
    vectors_all = data["embeddings"]
    if vectors_all is None or len(ids_all) < 3:
        raise ValueError("Index needs at least 3 embedded chunks. Run python main.py index")
    rng = np.random.default_rng(7)
    idx = np.sort(rng.choice(len(ids_all), size=min(sample, len(ids_all)), replace=False))
    ids = [ids_all[int(i)] for i in idx]
    metas = [data["metadatas"][int(i)] for i in idx]
    texts = [data["documents"][int(i)] for i in idx]
    vecs = unit_vectors(np.asarray(vectors_all)[idx])

    health = embedding_statistics(vecs, ids, metas)
    pca = PCA(n_components=2, random_state=7)
    coords = pca.fit_transform(vecs)
    kinds = [m.get("kind", "unknown") for m in metas]
    names = [m.get("source", "?") for m in metas]
    pages = [str(m.get("page", "?")) for m in metas]
    hovers = [t[:280].replace("\n", " ") for t in texts]

    query_nearest = []
    if query:
        qvec = unit_vectors(embeddings([query]))
        if qvec.shape[1] != vecs.shape[1]:
            raise RuntimeError("Query embedding dimensions differ; rebuild the index")
        qcoord = pca.transform(qvec)[0]
        cosine = (vecs @ qvec[0]).tolist()
        top = np.argsort(cosine)[::-1][:10]
        query_nearest = [
            {"id": ids[i], "source": names[i], "page": pages[i],
             "cosine_similarity": round(float(cosine[i]), 4)}
            for i in top
        ]
        coords = np.vstack([coords, qcoord])
        kinds.append("search query")
        names.append("QUERY")
        pages.append("–")
        ids.append("QUERY")
        hovers.append(query[:280])

    fig = px.scatter(
        x=coords[:, 0], y=coords[:, 1], color=kinds,
        hover_name=names,
        hover_data={
            "chunk_id": ids,
            "page": pages,
            "text": hovers,
        },
        labels={"x": "PCA component 1", "y": "PCA component 2", "color": "Corpus"},
        title="MDR RAG embedding map (PCA: visualization only)",
    )
    fig.update_traces(marker={"size": 8, "opacity": 0.78})
    fig.update_layout(legend_title="Dataset")
    health["pca_explained_variance_ratio"] = [round(float(v), 4) for v in pca.explained_variance_ratio_]
    health["pca_2d_total_explained_variance"] = round(float(sum(pca.explained_variance_ratio_)), 4)
    health["query"] = query
    health["query_nearest_by_cosine_in_sample"] = query_nearest
    health["sampling_note"] = f"Random deterministic subset {len(idx)} of {len(ids_all)} indexed chunks"
    dest = Path(destination) if destination else REPORTS / "embeddings.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(dest, include_plotlyjs=True)
    stats_path = dest.with_suffix(".json")
    stats_path.write_text(json.dumps(health, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Embedding map: {dest}\nEmbedding diagnostics: {stats_path}")
    return health
