"""Embed chunks and keep track of what is indexed."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Chunk, ChunkEmbedding, Document
from app.services.embeddings import Embedder
from app.services.vectors import to_bytes


def index_document(db: Session, embedder: Embedder, document_id: str, batch_size: int = 16) -> int:
    """Embed every chunk of this document that has no vector for the current model.
    Commits after each batch, so a failure part-way keeps the progress already made.
    Returns the number of chunks embedded."""
    model = embedder.model_name
    pending = db.scalars(
        select(Chunk)
        .outerjoin(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .where(Chunk.document_id == document_id)
        .where(or_(ChunkEmbedding.chunk_id.is_(None), ChunkEmbedding.model != model))
        .options(selectinload(Chunk.embedding))
        .order_by(Chunk.chunk_index)
    ).all()

    done = 0
    step = max(1, batch_size)
    for start in range(0, len(pending), step):
        batch = pending[start : start + step]
        vectors = embedder.embed_documents([chunk.text for chunk in batch])
        if len(vectors) != len(batch):
            raise ValueError("embedder returned the wrong number of vectors")
        for chunk, vector in zip(batch, vectors):
            data, dim = to_bytes(vector)
            if chunk.embedding is None:
                chunk.embedding = ChunkEmbedding(model=model, dim=dim, vector=data)
            else:  # re-index with a new model: update in place
                chunk.embedding.model = model
                chunk.embedding.dim = dim
                chunk.embedding.vector = data
        db.commit()
        done += len(batch)
    return done


def index_status(db: Session, model: str) -> dict:
    stmt = (
        select(
            Document.id,
            Document.filename,
            Document.chunk_count,
            func.count(ChunkEmbedding.chunk_id),
        )
        .select_from(Document)
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .outerjoin(
            ChunkEmbedding,
            and_(ChunkEmbedding.chunk_id == Chunk.id, ChunkEmbedding.model == model),
        )
        .group_by(Document.id, Document.filename, Document.chunk_count, Document.created_at)
        .order_by(Document.created_at)
    )
    documents = [
        {
            "document_id": doc_id,
            "filename": filename,
            "chunks": chunk_count,
            "indexed_chunks": indexed,
        }
        for doc_id, filename, chunk_count, indexed in db.execute(stmt).all()
    ]
    return {
        "model": model,
        "documents_total": len(documents),
        "documents_indexed": sum(1 for d in documents if d["indexed_chunks"] >= d["chunks"]),
        "chunks_total": sum(d["chunks"] for d in documents),
        "chunks_indexed": sum(d["indexed_chunks"] for d in documents),
        "documents": documents,
    }


def documents_needing_index(db: Session, model: str) -> list[str]:
    status = index_status(db, model)
    return [d["document_id"] for d in status["documents"] if d["indexed_chunks"] < d["chunks"]]
