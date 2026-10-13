"""Validate local inference settings at use time, without contacting Ollama."""
import os


def ollama_num_ctx() -> int:
    value = os.getenv("OLLAMA_NUM_CTX", "8192")
    try:
        result = int(value)
    except ValueError:
        raise ValueError("OLLAMA_NUM_CTX must be a positive integer") from None
    if result < 1:
        raise ValueError("OLLAMA_NUM_CTX must be a positive integer")
    return result
