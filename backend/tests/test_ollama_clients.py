import httpx
import pytest

from app.services.embeddings import OllamaEmbedder
from app.services.errors import EmbeddingUnavailable, LLMUnavailable
from app.services.llm import OllamaChat


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = ""

    def json(self):
        return self._body


def test_embedder_batches_and_adds_prefixes(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return FakeResponse(200, {"embeddings": [[1.0, 0.0] for _ in json["input"]]})

    monkeypatch.setattr(httpx, "post", fake_post)
    embedder = OllamaEmbedder("http://x:11434/", "nomic-embed-text", "doc: ", "query: ", batch_size=2)
    vectors = embedder.embed_documents(["a", "b", "c"])
    assert len(vectors) == 3
    assert [len(c[1]["input"]) for c in calls] == [2, 1]  # batching
    assert calls[0][0] == "http://x:11434/api/embed"
    assert calls[0][1]["input"] == ["doc: a", "doc: b"]
    embedder.embed_query("hello")
    assert calls[-1][1]["input"] == ["query: hello"]


def test_embedder_unreachable_gives_helpful_message(monkeypatch):
    def fake_post(url, json, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(EmbeddingUnavailable, match="ollama pull nomic-embed-text"):
        OllamaEmbedder("http://x:11434", "nomic-embed-text").embed_query("hi")


def test_embedder_missing_model_message(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda url, json, timeout: FakeResponse(404, {"error": "model 'zzz' not found"})
    )
    with pytest.raises(EmbeddingUnavailable, match="ollama pull zzz"):
        OllamaEmbedder("http://x:11434", "zzz").embed_query("hi")


def test_embedder_rejects_wrong_vector_count(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse(200, {"embeddings": []}))
    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbedder("http://x:11434", "m").embed_query("hi")


def test_chat_returns_content_and_sends_messages(monkeypatch):
    seen = {}

    def fake_post(url, json, timeout):
        seen.update(url=url, payload=json)
        return FakeResponse(200, {"message": {"content": "  Hello [1]  "}})

    monkeypatch.setattr(httpx, "post", fake_post)
    answer = OllamaChat("http://x:11434", "llama3.2:3b").generate("SYS", "USER")
    assert answer == "Hello [1]"
    assert seen["url"].endswith("/api/chat") and seen["payload"]["stream"] is False
    assert [m["role"] for m in seen["payload"]["messages"]] == ["system", "user"]


def test_chat_errors(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse(200, {"message": {"content": ""}}))
    with pytest.raises(LLMUnavailable):
        OllamaChat("http://x:11434", "m").generate("s", "u")

    def refuse(url, json, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", refuse)
    with pytest.raises(LLMUnavailable, match="Cannot reach Ollama"):
        OllamaChat("http://x:11434", "m").generate("s", "u")
