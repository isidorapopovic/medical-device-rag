"""Usage: python main.py --help"""
import argparse
import os
import sys

from dotenv import load_dotenv
from mdr_rag.core import ROOT

load_dotenv(ROOT / ".env")
from mdr_rag.pipeline import (  # noqa: E402
    extract_requirements, inspect_files, run_ask, run_index, run_review
)


def main():
    parser = argparse.ArgumentParser(description="EU MDR source-grounded regulatory research")
    parser.add_argument(
        "--retrieval", choices=["dense", "bm25", "hybrid"], default=None,
        help="Override RETRIEVAL_MODE for this command (place before the command)",
    )
    parser.add_argument(
        "--rerank", action="store_true",
        help="Use the local Ollama LLM to rerank retrieved candidates (slower)",
    )
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("inspect", help="List files and readable PDF pages")
    locate = subs.add_parser("locate", help="Find text to identify PDF page ranges")
    locate.add_argument("phrase", help='For example: "ANNEX I"')
    subs.add_parser("index", help="Rebuild the document vector index")
    ask = subs.add_parser("ask", help="Question-answering with verified source IDs")
    ask.add_argument("question")
    extract = subs.add_parser("extract", help="Draft requirements from ALL chunks on selected PDF pages")
    extract.add_argument("--pages", required=True, help='PDF page numbers, e.g. "89-92,94"')
    extract.add_argument("--legal-file", help="Filename in documents/legal")
    review = subs.add_parser("review", help="Map requirements to device evidence")
    review.add_argument("--limit", type=int, default=None, help="Only first N requirements (marks output partial)")
    review.add_argument("--k", type=int, default=7, help="Number of retrieved device chunks per requirement")
    explorer = subs.add_parser("explore", help="Show candidate passages to label manually")
    explorer.add_argument("question")
    explorer.add_argument("--kind", choices=["legal", "device"], default="legal")
    explorer.add_argument("--k", type=int, default=8)
    embedmap = subs.add_parser("visualize-embeddings", help="PCA scatter of stored vectors")
    embedmap.add_argument("--sample", type=int, default=600)
    embedmap.add_argument("--query", default=None)
    embedmap.add_argument("--out", default=None)
    evaluate = subs.add_parser("evaluate", help="Retrieval metrics against human-labeled gold")
    evaluate.add_argument("--gold", default=None)
    evaluate.add_argument("--ks", type=int, nargs="+", default=[3, 5, 10])
    evaluate.add_argument("--out", default=None)
    graph = subs.add_parser("graph", help="HTML citation provenance graph from assessment")
    graph.add_argument("--assessment", default=None)
    graph.add_argument("--out", default=None)
    graph.add_argument("--max-requirements", type=int, default=140)
    args = parser.parse_args()
    if args.retrieval is not None:
        os.environ["RETRIEVAL_MODE"] = args.retrieval
    if args.rerank:
        os.environ["RERANK_ENABLED"] = "true"
    try:
        if args.command == "inspect":
            inspect_files()
        elif args.command == "locate":
            inspect_files(args.phrase)
        elif args.command == "index":
            run_index()
        elif args.command == "ask":
            run_ask(args.question)
        elif args.command == "extract":
            extract_requirements(args.pages, args.legal_file)
        elif args.command == "review":
            run_review(args.limit, args.k)
        elif args.command == "explore":
            from mdr_rag.evaluation import inspect_candidates
            inspect_candidates(args.question, args.kind, args.k)
        elif args.command == "visualize-embeddings":
            from mdr_rag.embedding_viz import visualize_embeddings
            visualize_embeddings(args.sample, args.query, args.out)
        elif args.command == "evaluate":
            from mdr_rag.evaluation import evaluate
            evaluate(args.gold, args.ks, args.out)
        elif args.command == "graph":
            from mdr_rag.graph_viz import graph_from_assessment
            graph_from_assessment(args.assessment, args.out, args.max_requirements)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
