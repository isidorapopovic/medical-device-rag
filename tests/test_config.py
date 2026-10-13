import pytest

from mdr_rag import pipeline, search


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
@pytest.mark.parametrize("caller", ["draft", "rerank"])
def test_invalid_context_fails_before_inference(monkeypatch, value, caller):
    import ollama

    monkeypatch.setenv("OLLAMA_NUM_CTX", value)

    def unexpected_inference(**kwargs):
        pytest.fail("Invalid configuration must not reach Ollama")

    monkeypatch.setattr(ollama, "chat", unexpected_inference)
    with pytest.raises(ValueError, match="OLLAMA_NUM_CTX must be a positive integer"):
        if caller == "draft":
            pipeline.llm_parse("instructions", "synthetic input", pipeline.Finding)
        else:
            search.rerank_passages("query", [{"id": "A", "text": "synthetic"}])
