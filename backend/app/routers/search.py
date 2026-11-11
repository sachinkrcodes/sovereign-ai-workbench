"""Search and ask: find relevant passages, and (optionally) write a cited answer."""

import logging
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import enforce_token_budget, require_role
from app.models import User
from app.schemas import AskRequest, AskResponse, SearchHit, SearchRequest, SearchResponse, SourceOut
from app.services import audit, rag, retrieval, usage
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
    body: SearchRequest,
    request: Request,
    user: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
):
    hits, mode = retrieval.search(db, embedder, body.query, body.top_k, body.document_ids)
    audit.record(db, action="qa.search", user=user, detail={"query": audit.clip(body.query), "hits": len(hits)}, request=request)
    return SearchResponse(query=body.query, mode=mode, hits=[SearchHit(**_hit_out(h)) for h in hits])


@router.post("/ask", response_model=AskResponse)
def ask_question(
    body: AskRequest,
    request: Request,
    user: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    chat: ChatModel = Depends(get_chat),
    settings: Settings = Depends(get_settings),
):
    enforce_token_budget(db, user, settings, request)
    hits, retrieval_mode = retrieval.search(db, embedder, body.query, body.top_k, body.document_ids)

    def finish(response: AskResponse) -> AskResponse:
        audit.record(
            db, action="qa.ask", user=user,
            detail={"query": audit.clip(body.query), "mode": response.mode, "sources": len(response.sources)},
            request=request,
        )
        return response

    if not hits:
        return finish(
            AskResponse(
                query=body.query,
                mode="no_results",
                retrieval_mode=retrieval_mode,
                answer=rag.NOT_FOUND_TEXT,
                citations=[],
                sources=[],
                model=None,
                notice="No matching text found. Upload documents first, or try different words.",
            )
        )

    sources = [SourceOut(ref=i, **_hit_out(h)) for i, h in enumerate(hits, start=1)]
    started = time.perf_counter()
    try:
        answer, token_usage = chat.generate_with_usage(rag.SYSTEM_PROMPT, rag.build_user_prompt(body.query, hits))
    except LLMUnavailable as exc:
        logger.warning("chat model unavailable: %s", exc)
        return finish(
            AskResponse(
                query=body.query,
                mode="retrieval_only",
                retrieval_mode=retrieval_mode,
                answer=None,
                citations=[],
                sources=sources,
                model=None,
                notice=f"{exc} Showing the best matching passages instead.",
            )
        )

    usage.record_usage(
        db, user=user, kind="ask", model=chat.model_name,
        prompt_tokens=int(token_usage.get("prompt_tokens") or 0),
        completion_tokens=int(token_usage.get("completion_tokens") or 0),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )

    citations, invalid = rag.extract_citations(answer, len(sources))
    notices: list[str] = []
    if invalid:
        notices.append("Removed citations that pointed to sources which were not retrieved.")
    if not citations and rag.NOT_FOUND_TEXT not in answer:
        notices.append("The model did not cite any source. Treat this answer with caution.")
    return finish(
        AskResponse(
            query=body.query,
            mode="generated",
            retrieval_mode=retrieval_mode,
            answer=answer,
            citations=citations,
            sources=sources,
            model=chat.model_name,
            notice=" ".join(notices) or None,
        )
    )
