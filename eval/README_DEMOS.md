# Evaluation examples (NOT REAL MDR/device results)

These static HTML/JSON files were produced using synthetic data and mocked retrievers exclusively to verify rendering and file export. **They contain no analysis of real MDR provisions, medical device files, or compliance findings.** Numbers in `example_evaluation.json` are invented toy-data scores, not benchmark results for the application. Use `python main.py index`, then the documented `evaluate`, `visualize-embeddings`, and `graph` commands to produce results from your own documents.

- `example_embeddings.html`: illustrates a 2D PCA view of six toy vectors and a toy query.
- `example_evaluation.html`: illustrates dense/BM25/hybrid benchmark output on two toy questions.
- `example_graph.html`: illustrates requirement/evidence/document nodes with two fictional requirements.
- `gold_queries.EXAMPLE.json`: schema only; edit `gold_queries.json` to add verified relevant pages or chunk IDs from your actual documents.

The final project's code and test files, not these example metrics, are the deliverable.
