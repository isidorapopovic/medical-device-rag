"""Provenance-only requirement -> cited evidence -> source document graph.
No semantic facts or compliance judgments are inferred from edges.
"""
import json
from collections import Counter
from pathlib import Path

import networkx as nx
import plotly.graph_objects as go

from .core import REPORTS

STATUS_COLORS = {
    "supported": "#258f6c",
    "partial": "#e3a13b",
    "not_found": "#c95353",
    "needs_review": "#8664b5",
    "possibly_not_applicable": "#6e8192",
}


def build_evidence_graph(assessment):
    graph = nx.Graph()
    status_counts = Counter()
    linked = set()
    bad_citations = []
    for row in assessment.get("findings", []):
        req = row["requirement"]
        finding = row["finding"]
        rid = str(req["id"])
        status = finding["status"]
        status_counts[status] += 1
        req_node = "requirement:" + rid
        graph.add_node(req_node, kind="requirement", label=rid, status=status,
                       detail=req.get("requirement", ""), provision=req.get("provision", ""))
        retrieved = {x["id"]: x for x in row.get("retrieved_evidence", [])}
        for evidence_id in set(finding.get("evidence_ids", [])):
            if evidence_id not in retrieved:
                bad_citations.append({"requirement": rid, "id": evidence_id})
                continue
            evidence = retrieved[evidence_id]
            e_node = "evidence:" + evidence_id
            d_node = "document:" + evidence["source"]
            graph.add_node(e_node, kind="evidence", label=evidence_id,
                           detail=f"{evidence['source']}, page={evidence.get('page')}")
            graph.add_node(d_node, kind="document", label=Path(evidence["source"]).name,
                           detail=evidence["source"])
            graph.add_edge(req_node, e_node, relation="CITES_VERIFIED_ID")
            graph.add_edge(e_node, d_node, relation="EXTRACTED_FROM")
            linked.add(rid)
    all_requirements = sum(1 for _, a in graph.nodes(data=True) if a["kind"] == "requirement")
    doc_nodes = [n for n, a in graph.nodes(data=True) if a["kind"] == "document"]
    evidence_nodes = [n for n, a in graph.nodes(data=True) if a["kind"] == "evidence"]
    edge_count = sum(1 for _, _, a in graph.edges(data=True) if a["relation"] == "CITES_VERIFIED_ID")
    stats = {
        "assessed_requirements_in_graph": all_requirements,
        "requirements_with_cited_evidence": len(linked),
        "requirements_without_cited_evidence": all_requirements - len(linked),
        "citation_coverage_fraction": round(len(linked) / all_requirements, 4) if all_requirements else None,
        "unique_device_evidence_chunks": len(evidence_nodes),
        "unique_device_documents_cited": len(doc_nodes),
        "verified_requirement_to_evidence_edges": edge_count,
        "missing_citation_references": bad_citations,
        "status_counts": dict(status_counts),
        "partial_review": bool(assessment.get("partial_run", False)),
        "human_validated": bool(assessment.get("human_validated", False)),
        "warning": "This graph records citations in LLM findings, not proof that evidence satisfies requirements. The coverage fraction is NOT a regulatory compliance score."
    }
    return graph, stats


def draw_graph(graph, stats, destination=None, max_requirements=140):
    if max_requirements < 1:
        raise ValueError("max_requirements must be positive")
    reqs = [n for n, attrs in graph.nodes(data=True) if attrs["kind"] == "requirement"]
    shown = reqs[:max_requirements]
    keep = set(shown)
    for req in shown:
        for ev in graph.neighbors(req):
            keep.add(ev)
            for doc in graph.neighbors(ev):
                keep.add(doc)
    sub = graph.subgraph(keep).copy()
    if not sub:
        raise ValueError("No assessment findings to draw")
    pos = nx.spring_layout(sub, seed=17, iterations=60)
    edge_x, edge_y = [], []
    for a, b in sub.edges:
        edge_x.extend([pos[a][0], pos[b][0], None])
        edge_y.extend([pos[a][1], pos[b][1], None])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", name="Cited provenance",
                             hoverinfo="skip", line={"width": 0.8, "color": "#98a3ad"}))
    for status, color in STATUS_COLORS.items():
        group = [(n, d) for n, d in sub.nodes(data=True)
                 if d["kind"] == "requirement" and d["status"] == status]
        if not group:
            continue
        fig.add_trace(go.Scatter(
            x=[pos[n][0] for n, _ in group], y=[pos[n][1] for n, _ in group],
            text=[(d.get("label", "") + ": " + d.get("detail", ""))[:500] for n, d in group],
            hovertemplate="%{text}<extra></extra>",
            mode="markers", name="Requirement: " + status,
            marker={"size": 13, "color": color, "line": {"color": "white", "width": 0.5}},
        ))
    for kind, color, size in (("evidence", "#327cc2", 8), ("document", "#384450", 18)):
        group = [(n, d) for n, d in sub.nodes(data=True) if d["kind"] == kind]
        if not group:
            continue
        fig.add_trace(go.Scatter(
            x=[pos[n][0] for n, _ in group], y=[pos[n][1] for n, _ in group],
            text=[d.get("detail", "") for _, d in group],
            hovertemplate="%{text}<extra></extra>", mode="markers", name=kind,
            marker={"size": size, "color": color, "symbol": "diamond" if kind == "document" else "circle"},
        ))
    fig.update_layout(title="MDR requirement-to-evidence provenance graph (NOT proof of compliance)",
                      showlegend=True, height=800, hovermode="closest",
                      xaxis={"visible": False}, yaxis={"visible": False, "scaleanchor": "x"})
    path = Path(destination) if destination else REPORTS / "evidence_graph.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(path, include_plotlyjs=True)
    stats = dict(stats)
    stats["visualization_shows"] = len(shown)
    stats["visualization_omits"] = max(0, len(reqs) - len(shown))
    stats_path = path.with_suffix(".json")
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Evidence graph: {path}\nProvenance summary: {stats_path}")
    return stats


def graph_from_assessment(assessment_path=None, destination=None, max_requirements=140):
    assessment_path = Path(assessment_path) if assessment_path else REPORTS / "assessment.json"
    if not assessment_path.exists():
        raise FileNotFoundError(f"No assessment at {assessment_path}; first run python main.py review")
    assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    graph, stats = build_evidence_graph(assessment)
    return draw_graph(graph, stats, destination, max_requirements)
