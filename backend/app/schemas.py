"""API response shapes (what the frontend receives)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    char_count: int
    chunk_count: int
    created_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_index: int
    page_number: int | None
    text: str
    char_count: int


class ChunkList(BaseModel):
    document_id: str
    items: list[ChunkOut]
    total: int
    limit: int
    offset: int


# ---------- search / ask / indexing (stage 2) ----------


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] | None = Field(default=None, max_length=50)


class SearchHit(BaseModel):
    chunk_id: int
    document_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    text: str
    score: float
    vector_score: float | None
    keyword_score: float | None


class SearchResponse(BaseModel):
    query: str
    mode: str  # "hybrid" (meaning + keywords) or "keyword_only"
    hits: list[SearchHit]


class SourceOut(SearchHit):
    ref: int  # the [n] number used in the answer


class AskRequest(SearchRequest):
    pass


class AskResponse(BaseModel):
    query: str
    mode: str  # "generated", "retrieval_only" or "no_results"
    retrieval_mode: str
    answer: str | None
    citations: list[int]
    sources: list[SourceOut]
    model: str | None
    notice: str | None


class IndexedDocument(BaseModel):
    document_id: str
    filename: str
    chunks: int
    indexed_chunks: int


class IndexStatus(BaseModel):
    model: str
    documents_total: int
    documents_indexed: int
    chunks_total: int
    chunks_indexed: int
    documents: list[IndexedDocument]


class IndexResult(BaseModel):
    model: str
    documents_processed: int
    chunks_indexed: int


# ---------- agents (stage 3) ----------


class AgentInfo(BaseModel):
    name: str
    title: str
    description: str
    allowed_tools: list[str]
    max_steps: int


class AgentRunRequest(BaseModel):
    task: str = Field(min_length=3, max_length=2000)


class AgentStepOut(BaseModel):
    step: int
    tool: str
    arguments: dict
    status: str  # ok | denied | error
    output_preview: str
    duration_ms: int


class AgentSourceOut(BaseModel):
    filename: str
    page: int | None


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent: str
    task: str
    status: str
    answer: str | None
    steps: list[AgentStepOut]
    sources: list[AgentSourceOut]
    model: str | None
    error: str | None
    duration_ms: int
    created_at: datetime


class AgentRunList(BaseModel):
    items: list[AgentRunOut]
    total: int
    limit: int
    offset: int
