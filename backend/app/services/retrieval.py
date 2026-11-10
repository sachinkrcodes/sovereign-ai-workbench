"""Find the most relevant chunks for a question.

Hybrid search = two rankings merged:
  1. Keyword ranking (BM25): great for exact terms like "P-101" or "Section 4.2".
  2. Meaning ranking (vector cosine similarity): great for different wording of the same idea.
They are merged with Reciprocal Rank Fusion, which needs no tuning and is robust.

If Ollama is down or nothing is indexed yet, search still works using keywords only."""

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, ChunkEmbedding, Document
from app.services.embeddings import Embedder
from app.services.errors import EmbeddingUnavailable
from app.services.vectors import from_bytes, normalise

VECTOR_CANDIDATES = 50
RRF_K = 60


@dataclass
class Hit:
    chunk_id: int
    document_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    text: str
    score: float
    vector_score: float | None
    keyword_score: float | None


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def bm25_scores(
    query_tokens: list[str], docs_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75
) -> list[float]:
    n = len(docs_tokens)
    if n == 0:
        return []
    avg_len = (sum(len(d) for d in docs_tokens) / n) or 1.0
    doc_freq: Counter = Counter()
    for tokens in docs_tokens:
        doc_freq.update(set(tokens))
    unique_query = set(query_tokens)

    scores: list[float] = []
    for tokens in docs_tokens:
        tf = Counter(tokens)
        length = len(tokens)
        score = 0.0
        for term in unique_query:
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * length / avg_len))
        scores.append(score)
    return scores


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return fused


def search(
    db: Session,
    embedder: Embedder,
    query: str,
    top_k: int = 5,
    document_ids: list[str] | None = None,
) -> tuple[list[Hit], str]:
    """Returns (hits, mode) where mode is "hybrid" or "keyword_only"."""
    stmt = select(
        Chunk.id,
        Chunk.document_id,
        Chunk.page_number,
        Chunk.chunk_index,
        Chunk.text,
        Document.filename,
    ).join(Document, Document.id == Chunk.document_id)
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    rows = db.execute(stmt).all()
    if not rows:
        return [], "keyword_only"
    by_id = {row.id: row for row in rows}

    # 1) keyword ranking
    keyword_scores: dict[int, float] = {}
    query_tokens = tokenize(query)
    if query_tokens:
        scores = bm25_scores(query_tokens, [tokenize(row.text) for row in rows])
        keyword_scores = {row.id: s for row, s in zip(rows, scores) if s > 0}
    keyword_rank = sorted(keyword_scores, key=keyword_scores.get, reverse=True)

    # 2) meaning ranking (only if chunks were indexed with the current embedding model)
    vector_scores: dict[int, float] = {}
    mode = "keyword_only"
    emb_stmt = (
        select(ChunkEmbedding.chunk_id, ChunkEmbedding.vector, ChunkEmbedding.dim)
        .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
        .where(ChunkEmbedding.model == embedder.model_name)
    )
    if document_ids:
        emb_stmt = emb_stmt.where(Chunk.document_id.in_(document_ids))
    emb_rows = db.execute(emb_stmt).all()
    if emb_rows:
        try:
            query_vector = normalise(embedder.embed_query(query))
        except EmbeddingUnavailable:
            query_vector = None
        if query_vector is not None:
            usable = [r for r in emb_rows if r.dim == query_vector.shape[0]]
            if usable:
                matrix = np.vstack([from_bytes(r.vector) for r in usable])
                similarities = matrix @ query_vector
                order = np.argsort(-similarities)[:VECTOR_CANDIDATES]
                vector_scores = {usable[i].chunk_id: float(similarities[i]) for i in order}
                mode = "hybrid"
    vector_rank = sorted(vector_scores, key=vector_scores.get, reverse=True)

    fused = reciprocal_rank_fusion([r for r in (keyword_rank, vector_rank) if r])
    best = sorted(fused, key=fused.get, reverse=True)[:top_k]

    hits = [
        Hit(
            chunk_id=cid,
            document_id=by_id[cid].document_id,
            filename=by_id[cid].filename,
            page_number=by_id[cid].page_number,
            chunk_index=by_id[cid].chunk_index,
            text=by_id[cid].text,
            score=round(fused[cid], 5),
            vector_score=round(vector_scores[cid], 4) if cid in vector_scores else None,
            keyword_score=round(keyword_scores[cid], 4) if cid in keyword_scores else None,
        )
        for cid in best
    ]
    return hits, mode
