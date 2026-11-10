"""File storage behind a tiny interface.

Stage 1 stores files on local disk. Stage 6 adds an S3Storage class with the same three
methods, so nothing else in the project has to change when we move to AWS."""

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Storage(Protocol):
    def save(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Safety: never allow a key to escape the storage folder (path traversal).
        if path.parent != self.root:
            raise ValueError("invalid storage key")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        # Write to a temp file first, then rename: a crash never leaves a half-written file.
        fd, tmp_name = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(data)
            os.replace(tmp_name, path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


@lru_cache
def _default_storage() -> LocalStorage:
    return LocalStorage(get_settings().storage_dir)


def get_storage() -> Storage:
    """FastAPI dependency."""
    return _default_storage()
