"""Errors for the local AI engine, with messages that are safe and helpful to show users."""


class AIUnavailableError(Exception):
    """Ollama is not reachable, or a model is missing."""


class EmbeddingUnavailable(AIUnavailableError):
    pass


class LLMUnavailable(AIUnavailableError):
    pass


def unreachable_message(base_url: str, model: str) -> str:
    return (
        f"Cannot reach Ollama at {base_url}. Start Ollama, then make sure the model is installed "
        f"(run: ollama pull {model})."
    )


def describe_ollama_http_error(response, model: str) -> str:
    """Turn an Ollama HTTP error response into one clear sentence."""
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("error", ""))
    except Exception:
        detail = (getattr(response, "text", "") or "")[:200]
    if response.status_code == 404 or "not found" in detail.lower():
        return f"Model '{model}' is not installed in Ollama. Run: ollama pull {model}"
    return f"Ollama returned an error ({response.status_code}): {detail or 'no details'}"
