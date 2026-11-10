"""Chat model (the part that writes answers) running in Ollama on your own machine."""

from functools import lru_cache
from typing import Protocol

import httpx

from app.config import get_settings
from app.services.errors import LLMUnavailable, describe_ollama_http_error, unreachable_message


class ChatModel(Protocol):
    model_name: str

    def generate(self, system: str, user: str) -> str: ...


class OllamaChat:
    def __init__(self, base_url: str, model: str, timeout: float = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.timeout = timeout

    def generate(self, system: str, user: str) -> str:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 4096},
        }
        try:
            response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise LLMUnavailable(unreachable_message(self.base_url, self.model_name)) from exc
        if response.status_code != 200:
            raise LLMUnavailable(describe_ollama_http_error(response, self.model_name))
        message = response.json().get("message") or {}
        content = (message.get("content") or "").strip()
        if not content:
            raise LLMUnavailable("The model returned an empty answer. Try again.")
        return content


@lru_cache
def _default_chat() -> OllamaChat:
    s = get_settings()
    return OllamaChat(s.ollama_base_url, s.chat_model, s.ai_timeout_seconds)


def get_chat() -> ChatModel:
    """FastAPI dependency."""
    return _default_chat()
