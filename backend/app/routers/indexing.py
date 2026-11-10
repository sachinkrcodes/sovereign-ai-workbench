"""Index documents: turn their chunks into vectors so they can be searched by meaning."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Document
from app.schemas import IndexResult, IndexStatus
from app.services import indexing
from app.services.embeddings import Embedder, get_embedder
from app.services.errors import EmbeddingUnavailable

router = APIRouter(prefix="/api/v1", tags=["indexing"])


@router.get("/index/status", response_model=IndexStatus)
def index_status(db: Session = Depends(get_db), embedder: Embedder = Depends(get_embedder)):
    return indexing.index_status(db, embedder.model_name)


@router.post("/index", response_model=IndexResult)
def index_all_pending(
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
):
    """Index every document that is not fully indexed yet (safe to call repeatedly)."""
    pending = indexing.documents_needing_index(db, embedder.model_name)
    total = 0
    try:
        for document_id in pending:
            total += indexing.index_document(db, embedder, document_id, settings.embed_batch_size)
    except EmbeddingUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return IndexResult(model=embedder.model_name, documents_processed=len(pending), chunks_indexed=total)


@router.post("/documents/{document_id}/index", response_model=IndexResult)
def index_one(
    document_id: str,
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
):
    if db.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        count = indexing.index_document(db, embedder, document_id, settings.embed_batch_size)
    except EmbeddingUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return IndexResult(model=embedder.model_name, documents_processed=1, chunks_indexed=count)
