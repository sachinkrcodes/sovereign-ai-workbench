"""Search and ask: find relevant passages, and (optionally) write a cited answer."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AskRequest, AskResponse, SearchHit, SearchRequest, SearchResponse, SourceOut
from app.services import rag, retrieval
from app.services.embeddings import Embedder, get_embedder
from app.services.errors import LLMUnavailable
from app.services.llm import ChatModel, get_chat

logger = logging.getLogger("app.search")
router = APIRouter(prefix="/api/v1", tags=["search"])


def _hit_out(hit: retrieval.Hit) -> dict:
    return {
        "chunk_id": hit.chunk_id,
        "document_id": hit.document_id,
        "filename": hit.filename,
        "page_number": hit.page_number,
        "chunk_index": hit.chunk_index,
        "text": hit.text,
        "score": hit.score,
        "vector_score": hit.vector_score,
        "keyword_score": hit.keyword_score,
    }


@router.post("/search", response_model=SearchResponse)
def search_documents(
    request: SearchRequest,
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
):
    hits, mode = retrieval.search(db, embedder, request.query, request.top_k, request.document_ids)
    return SearchResponse(query=request.query, mode=mode, hits=[SearchHit(**_hit_out(h)) for h in hits])


@router.post("/ask", response_model=AskResponse)
def ask_question(
    request: AskRequest,
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    chat: ChatModel = Depends(get_chat),
):
    hits, retrieval_mode = retrieval.search(
        db, embedder, request.query, request.top_k, request.document_ids
    )
    if not hits:
        return AskResponse(
            query=request.query,
            mode="no_results",
            retrieval_mode=retrieval_mode,
            answer=rag.NOT_FOUND_TEXT,
            citations=[],
            sources=[],
            model=None,
            notice="No matching text found. Upload documents first, or try different words.",
        )

    sources = [SourceOut(ref=i, **_hit_out(h)) for i, h in enumerate(hits, start=1)]
    try:
        answer = chat.generate(rag.SYSTEM_PROMPT, rag.build_user_prompt(request.query, hits))
    except LLMUnavailable as exc:
        logger.warning("chat model unavailable: %s", exc)
        return AskResponse(
            query=request.query,
            mode="retrieval_only",
            retrieval_mode=retrieval_mode,
            answer=None,
            citations=[],
            sources=sources,
            model=None,
            notice=f"{exc} Showing the best matching passages instead.",
        )

    citations, invalid = rag.extract_citations(answer, len(sources))
    notices: list[str] = []
    if invalid:
        notices.append("Removed citations that pointed to sources which were not retrieved.")
    if not citations and rag.NOT_FOUND_TEXT not in answer:
        notices.append("The model did not cite any source. Treat this answer with caution.")
    return AskResponse(
        query=request.query,
        mode="generated",
        retrieval_mode=retrieval_mode,
        answer=answer,
        citations=citations,
        sources=sources,
        model=chat.model_name,
        notice=" ".join(notices) or None,
    )
