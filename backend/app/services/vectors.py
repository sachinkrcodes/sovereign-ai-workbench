"""Tiny helpers to store vectors as bytes and compare them."""

import numpy as np


def to_bytes(vector) -> tuple[bytes, int]:
    """Normalise to length 1 (so a dot product equals cosine similarity) and pack as float32."""
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0:
        arr = arr / norm
    arr = arr.astype(np.float32)
    return arr.tobytes(), int(arr.shape[0])


def from_bytes(data) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32)


def normalise(vector) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return (arr / norm).astype(np.float32) if norm > 0 else arr
