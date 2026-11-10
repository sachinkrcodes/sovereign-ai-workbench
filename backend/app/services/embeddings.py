"""Turn text into vectors (embeddings) using a model running in Ollama on your own machine."""

from functools import lru_cache
from typing import Protocol

import httpx

from app.config import get_settings
from app.services.errors import EmbeddingUnavailable, describe_ollama_http_error, unreachable_message


class Embedder(Protocol):
    model_name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        doc_prefix: str = "",
        query_prefix: str = "",
        timeout: float = 180,
        batch_size: int = 16,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.doc_prefix = doc_prefix
        self.query_prefix = query_prefix
        self.timeout = timeout
        self.batch_size = max(1, batch_size)

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        try:
            response = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model_name, "input": inputs},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(unreachable_message(self.base_url, self.model_name)) from exc
        if response.status_code != 200:
            raise EmbeddingUnavailable(describe_ollama_http_error(response, self.model_name))
        vectors = response.json().get("embeddings")
        if not vectors or len(vectors) != len(inputs):
            raise EmbeddingUnavailable("Ollama returned an unexpected embedding response.")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [self.doc_prefix + t for t in texts[start : start + self.batch_size]]
            vectors.extend(self._embed(batch))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.query_prefix + text])[0]


@lru_cache
def _default_embedder() -> OllamaEmbedder:
    s = get_settings()
    return OllamaEmbedder(
        base_url=s.ollama_base_url,
        model=s.embedding_model,
        doc_prefix=s.embedding_doc_prefix,
        query_prefix=s.embedding_query_prefix,
        timeout=s.ai_timeout_seconds,
        batch_size=s.embed_batch_size,
    )


def get_embedder() -> Embedder:
    """FastAPI dependency."""
    return _default_embedder()
