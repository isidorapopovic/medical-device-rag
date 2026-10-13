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
    "insufficient_evidence": "#9c6841",
    "pending": "#a4a9af",
    "failed": "#b43f49",
    "stale": "#d18c37",
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
    cited_device_chunks, cited_device_docs = set(), set()
    for row in assessment.get("findings", []):
        req = row["requirement"]
        finding = row["finding"]
        rid = str(req["id"])
        status = finding["status"]
        status_counts[status] += 1
        req_node = "requirement:" + rid
        graph.add_node(req_node, kind="requirement", label=rid, status=status,
                       detail=req.get("requirement", ""), provision=req.get("provision", ""),
                       execution_status=row.get("execution_status", "completed"), audit=row.get("audit_status", "legacy_unverified"),
                       applicability=(row.get("applicability") or {}).get("status", "unverified legacy"))
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
            cited_device_chunks.add(evidence_id)
            cited_device_docs.add(evidence["source"])
    assessed = len({str(row["requirement"]["id"]) for row in assessment.get("findings", [])})
    for rid, section in assessment.get("sections", {}).items():
        node = "requirement:" + rid
        if node not in graph:
            graph.add_node(node, kind="requirement", label=rid,
                status=section["execution_status"] if section["execution_status"] in {"pending", "failed", "stale"} else "pending",
                detail=section.get("requirement", {}).get("requirement", ""))
        graph.nodes[node].update(execution_status=section["execution_status"], audit=section.get("audit_status", "not_performed"),
            applicability=(section.get("applicability") or {}).get("status", "unverified"),
            gate=(section.get("evidence_gate") or {}).get("reason", "not_performed"),
            gate_mode=(section.get("evidence_gate") or {}).get("mode", "not_performed"),
            strict_gate_passed=(section.get("evidence_gate") or {}).get("strict_validation_passed", False),
            calibration=(section.get("evidence_gate") or {}).get("calibration_fingerprint"))
    from .source_buffer import SourceBuffer, PresentedPassage
    buffer = SourceBuffer(assessment.get("source_buffer", {}))
    def edge(a, b, relation, claim_id=None):
        previous = graph.get_edge_data(a, b, {})
        relations = list(dict.fromkeys(previous.get("relations", [previous["relation"]] if previous else []) + [relation]))
        claims = list(dict.fromkeys(previous.get("claim_ids", []) + ([claim_id] if claim_id else [])))
        graph.add_edge(a, b, relation=relations[0], relations=relations, claim_ids=claims)
    def snapshot(key):
        passage = buffer.get_passage(key)
        node, document = "snapshot:" + key, "source-document:" + passage.kind + ":" + passage.source
        graph.add_node(node, kind="evidence", label=passage.chunk_id, buffer_id=key, corpus_role=passage.kind,
            detail=f"{passage.kind}: {passage.source}; {passage.locator}; page={passage.page}; block={passage.block}; SHA-256={passage.file_sha256}")
        graph.add_node(document, kind="document", label=Path(passage.source).name, detail=passage.source, corpus_role=passage.kind)
        edge(node, document, "EXTRACTED_FROM")
        return node
    for rid, section in assessment.get("sections", {}).items():
        for key in section.get("retrieved_buffer_ids", []):
            edge("requirement:" + rid, snapshot(key), "RETRIEVED")
    calls = {c["call_id"]: c for c in assessment.get("model_calls", [])}
    for row in assessment.get("findings", []):
        node = "requirement:" + row["requirement"]["id"]
        call = calls.get(row.get("draft_call_id"))
        for link in row.get("claim_links", []):
            try:
                context = [PresentedPassage.model_validate(p) for p in call["presented"]] if call and call["outcome"] == "completed" else None
                buffer.validate_link(link, presented=context)
            except ValueError:
                bad_citations.append({"requirement": row["requirement"]["id"], "id": link.get("chunk_id"), "reason": "invalid_raw_link"})
                continue
            target = snapshot(link["buffer_id"])
            relation = "CONTRADICTION" if link["purpose"] == "contradiction" else "RAW_CITED"
            edge(node, target, relation, link["claim_id"])
            if row.get("audit_status") == "semantic_checked" and context is not None and link["purpose"] == "device_support":
                edge(node, target, "AUDITED_SUPPORT", link["claim_id"])
        for link in (row.get("applicability") or {}).get("legal_citations", []):
            buffer.validate_link(link)
            edge(node, snapshot(link["buffer_id"]), "LEGAL_SCOPE")
    all_requirements = sum(1 for _, a in graph.nodes(data=True) if a["kind"] == "requirement")
    edge_count = sum(1 for _, _, a in graph.edges(data=True) if a["relation"] == "CITES_VERIFIED_ID")
    relation_counts = Counter(relation for _, _, a in graph.edges(data=True) for relation in a.get("relations", [a["relation"]]))
    stats = {
        "assessed_requirements_in_graph": assessed,
        "total_requirements_in_graph": all_requirements,
        "unassessed_requirements_in_graph": all_requirements - assessed,
        "requirements_with_cited_evidence": len(linked),
        "requirements_without_cited_evidence": assessed - len(linked),
        "citation_coverage_fraction": round(len(linked) / assessed, 4) if assessed else None,
        "unique_device_evidence_chunks": len(cited_device_chunks),
        "unique_device_documents_cited": len(cited_device_docs),
        "verified_requirement_to_evidence_edges": edge_count,
        "missing_citation_references": bad_citations,
        "status_counts": dict(status_counts),
        "execution_counts": dict(Counter(a.get("execution_status", "completed") for _, a in graph.nodes(data=True) if a["kind"] == "requirement")),
        "applicability_counts": dict(Counter(a.get("applicability", "unverified") for _, a in graph.nodes(data=True) if a["kind"] == "requirement")),
        "audit_counts": dict(Counter(a.get("audit", "not_performed") for _, a in graph.nodes(data=True) if a["kind"] == "requirement")),
        "relation_counts": dict(relation_counts),
        "gate_modes": dict(Counter(a.get("gate_mode", "legacy_unverified") for _, a in graph.nodes(data=True) if a["kind"] == "requirement")),
        "strict_gate_passed_requirements": sum(bool(a.get("strict_gate_passed")) for _, a in graph.nodes(data=True) if a["kind"] == "requirement"),
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
    fig = go.Figure()
    edge_styles = {"AUDITED_SUPPORT": ("#258f6c", "solid"), "CONTRADICTION": ("#c95353", "solid"),
                   "RAW_CITED": ("#327cc2", "solid"), "LEGAL_SCOPE": ("#8664b5", "solid"),
                   "RETRIEVED": ("#a4a9af", "dot"), "CITES_VERIFIED_ID": ("#327cc2", "solid"),
                   "EXTRACTED_FROM": ("#98a3ad", "solid")}
    groups = {}
    for a, b, attrs in sub.edges(data=True):
        relations = attrs.get("relations", [attrs["relation"]])
        relation = next((r for r in edge_styles if r in relations), "EXTRACTED_FROM")
        xs, ys = groups.setdefault(relation, ([], []))
        xs.extend([pos[a][0], pos[b][0], None]); ys.extend([pos[a][1], pos[b][1], None])
    for relation, (xs, ys) in groups.items():
        color, dash = edge_styles[relation]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=relation,
            hoverinfo="skip", line={"width": 1, "color": color, "dash": dash}))
    for status, color in STATUS_COLORS.items():
        group = [(n, d) for n, d in sub.nodes(data=True)
                 if d["kind"] == "requirement" and d["status"] == status]
        if not group:
            continue
        fig.add_trace(go.Scatter(
            x=[pos[n][0] for n, _ in group], y=[pos[n][1] for n, _ in group],
            text=[(d.get("label", "") + ": " + d.get("detail", "") + f"; execution={d.get('execution_status')}; audit={d.get('audit')}; applicability={d.get('applicability')}; gate={d.get('gate_mode', 'legacy')}/{d.get('gate', 'legacy')}; strict gate passed={d.get('strict_gate_passed', False)}; calibration={d.get('calibration') or 'NONE'}" )[:700] for n, d in group],
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
