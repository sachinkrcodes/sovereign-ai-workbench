"""Split document text into overlapping chunks for semantic search (RAG).

Rules: keep paragraphs together when possible, never cross a page boundary (so every chunk
has an exact page number for citations), and overlap long paragraphs so no sentence loses
its context at a cut."""

import re
from dataclasses import dataclass

from app.services.extract import PageText


@dataclass(frozen=True)
class ChunkData:
    chunk_index: int
    page_number: int | None
    text: str


def _hard_split(text: str, size: int, overlap: int) -> list[str]:
    """Cut one very long paragraph, preferring to break on a space."""
    pieces: list[str] = []
    start, length = 0, len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            cut = text.rfind(" ", start + int(size * 0.6), end)
            if cut != -1:
                end = cut
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)  # always move forward
    return pieces


def split_text(text: str, size: int, overlap: int) -> list[str]:
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("invalid chunk settings")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(paragraph, size, overlap))
        elif not current:
            current = paragraph
        elif len(current) + 2 + len(paragraph) <= size:
            current += "\n\n" + paragraph
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def chunk_pages(pages: list[PageText], size: int, overlap: int) -> list[ChunkData]:
    result: list[ChunkData] = []
    for page in pages:
        for piece in split_text(page.text, size, overlap):
            result.append(ChunkData(len(result), page.page_number, piece))
    return result
