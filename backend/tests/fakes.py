"""Stand-ins for Ollama so tests run fast, offline and deterministically."""

import re
import zlib

from app.services.errors import EmbeddingUnavailable, LLMUnavailable


class HashEmbedder:
    """Turns text into a 256-number vector by hashing words. Texts that share words get
    similar vectors, which is enough to test the whole search pipeline."""

    def __init__(self, dim: int = 256) -> None:
        self.model_name = "hash-test"
        self.dim = dim
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise EmbeddingUnavailable("Ollama is down (test).")

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in re.findall(r"\w+", text.lower()):
            vector[zlib.crc32(token.encode()) % self.dim] += 1.0
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._check()
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self._check()
        return self._vector(text)


class FakeChat:
    def __init__(self) -> None:
        self.model_name = "fake-chat"
        self.reply = "Answer text [1]."
        self.fail = False
        self.last_system = ""
        self.last_user = ""
        # Scripted replies for agent tests: each call to chat() pops the next message.
        self.tool_turns: list[dict] = []
        self.chat_calls: list[tuple[int, list | None]] = []

    def generate(self, system: str, user: str) -> str:
        if self.fail:
            raise LLMUnavailable("Cannot reach Ollama (test).")
        self.last_system, self.last_user = system, user
        return self.reply

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if self.fail:
            raise LLMUnavailable("Cannot reach Ollama (test).")
        self.chat_calls.append((len(messages), tools))
        if self.tool_turns:
            return self.tool_turns.pop(0)
        return {"role": "assistant", "content": "Done."}
