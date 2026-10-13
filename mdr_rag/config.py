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


def ollama_gpu_layers():
    value = os.getenv("OLLAMA_NUM_GPU", "").strip()
    if not value:
        return None
    try:
        result = int(value)
    except ValueError:
        raise ValueError("OLLAMA_NUM_GPU must be a nonnegative integer or blank") from None
    if result < 0:
        raise ValueError("OLLAMA_NUM_GPU must be a nonnegative integer or blank")
    return result


def ollama_device_options():
    value = ollama_gpu_layers()
    return {"num_gpu": value} if value is not None else {}
