"""Chat model (the part that writes answers and drives agents) running in Ollama on your machine."""

from functools import lru_cache
from typing import Protocol

import httpx

from app.config import get_settings
from app.services.errors import LLMUnavailable, describe_ollama_http_error, unreachable_message


class ChatModel(Protocol):
    model_name: str

    def generate(self, system: str, user: str) -> str: ...
    def generate_with_usage(self, system: str, user: str) -> tuple[str, dict]: ...
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


class OllamaChat:
    def __init__(self, base_url: str, model: str, timeout: float = 180, num_ctx: int = 6144) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.timeout = timeout
        self.num_ctx = num_ctx

    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 450) -> dict:
        """Send a conversation, get back the assistant message (may contain tool_calls)."""
        payload: dict = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",  # keep the model in memory between questions (default is 5 minutes)
            "options": {"temperature": 0.1, "num_ctx": self.num_ctx, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = tools
        try:
            response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise LLMUnavailable(unreachable_message(self.base_url, self.model_name)) from exc
        if response.status_code != 200:
            raise LLMUnavailable(describe_ollama_http_error(response, self.model_name))
        data = response.json()
        message = data.get("message") or {}
        # Ollama reports how many tokens it read and wrote; we keep them for usage tracking.
        message["usage"] = {
            "prompt_tokens": int(data.get("prompt_eval_count") or 0),
            "completion_tokens": int(data.get("eval_count") or 0),
        }
        if not (message.get("content") or "").strip() and not message.get("tool_calls"):
            raise LLMUnavailable("The model returned an empty answer. Try again.")
        return message

    def generate_with_usage(self, system: str, user: str) -> tuple[str, dict]:
        message = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=350
        )
        return (message.get("content") or "").strip(), message.get("usage") or {}

    def generate(self, system: str, user: str) -> str:
        return self.generate_with_usage(system, user)[0]


@lru_cache
def _default_chat() -> OllamaChat:
    s = get_settings()
    return OllamaChat(s.ollama_base_url, s.chat_model, s.ai_timeout_seconds, s.chat_context_tokens)


def get_chat() -> ChatModel:
    """FastAPI dependency."""
    return _default_chat()


def warm_up() -> None:
    """Load both models into memory at startup so the first real question is not slow."""
    from app.services.embeddings import get_embedder

    try:
        get_embedder().embed_query("warm up")
        get_chat().chat([{"role": "user", "content": "Reply with OK."}], max_tokens=2)
    except Exception:  # Ollama not running yet: nothing to warm up
        pass
