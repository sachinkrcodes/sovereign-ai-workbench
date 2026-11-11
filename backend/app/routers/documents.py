"""Document endpoints: upload, list, inspect, delete."""

import hashlib
import logging
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import require_role
from app.models import Chunk, Document, User
from app.schemas import ChunkList, DocumentList, DocumentOut
from app.services import audit
from app.services.chunking import chunk_pages
from app.services.extract import ExtractionError, extract_document, sniff_matches
from app.services.storage import Storage, get_storage

logger = logging.getLogger("app.documents")
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md"}


def _safe_filename(raw: str | None) -> str:
    """Keep only the file name (no folders), strip control characters, limit length."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if not name:
        raise HTTPException(status_code=400, detail="File name is missing.")
    return name[:255]


def _get_or_404(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT or MD file")],
    request: Request,
    user: User = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
):
    filename = _safe_filename(file.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    # Read at most limit+1 bytes: enough to detect "too big" without loading a huge file.
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413, detail=f"File is larger than {settings.max_upload_mb} MB."
        )
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if not sniff_matches(ext, data):
        raise HTTPException(
            status_code=415, detail="File content does not match its extension."
        )

    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Document).where(Document.sha256 == digest))
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"message": "This exact file was already uploaded.", "document_id": existing.id},
        )

    try:
        extracted = extract_document(ext, data)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    chunk_data = chunk_pages(extracted.pages, settings.chunk_size, settings.chunk_overlap)
    if not chunk_data:
        raise HTTPException(status_code=422, detail="No usable text found in this file.")

    document_id = uuid.uuid4().hex
    storage_key = f"{document_id}.{ext}"
    document = Document(
        id=document_id,
        filename=filename,
        file_type=ext,
        size_bytes=len(data),
        sha256=digest,
        storage_key=storage_key,
        page_count=extracted.page_count,
        char_count=sum(len(c.text) for c in chunk_data),
        chunk_count=len(chunk_data),
        uploaded_by=user.id,
        chunks=[
            Chunk(
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                text=c.text,
                char_count=len(c.text),
            )
            for c in chunk_data
        ],
    )

    db.add(document)
    try:
        db.flush()
        storage.save(storage_key, data)
        db.commit()
    except IntegrityError:
        # Two identical uploads raced each other; the unique hash caught the second one.
        db.rollback()
        storage.delete(storage_key)
        raise HTTPException(status_code=409, detail="This exact file was already uploaded.")
    except Exception:
        db.rollback()
        storage.delete(storage_key)
        logger.exception("upload failed for %s", filename)
        raise

    logger.info("uploaded document=%s type=%s chunks=%d", document.id, ext, len(chunk_data))
    audit.record(
        db, action="document.upload", user=user, resource_type="document", resource_id=document.id,
        detail={"filename": filename, "size_bytes": len(data), "chunks": len(chunk_data)}, request=request,
    )
    return document


@router.get("", response_model=DocumentList, dependencies=[Depends(require_role("viewer"))])
def list_documents(
    q: Annotated[str | None, Query(max_length=100, description="Search in file name")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    stmt = select(Document)
    count_stmt = select(func.count()).select_from(Document)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        condition = Document.filename.ilike(f"%{escaped}%", escape="\\")
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = db.scalar(count_stmt) or 0
    items = db.scalars(
        stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return DocumentList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentOut, dependencies=[Depends(require_role("viewer"))])
def get_document(document_id: str, db: Session = Depends(get_db)):
    return _get_or_404(db, document_id)


@router.get("/{document_id}/chunks", response_model=ChunkList, dependencies=[Depends(require_role("viewer"))])
def get_document_chunks(
    document_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    document = _get_or_404(db, document_id)
    items = db.scalars(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index)
        .offset(offset)
        .limit(limit)
    ).all()
    return ChunkList(
        document_id=document_id,
        items=items,
        total=document.chunk_count,
        limit=limit,
        offset=offset,
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    request: Request,
    user: User = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    document = _get_or_404(db, document_id)
    storage_key = document.storage_key
    filename = document.filename
    db.delete(document)  # chunks are deleted with it (cascade)
    db.commit()
    try:
        storage.delete(storage_key)
    except Exception:
        logger.exception("could not remove stored file %s", storage_key)
    audit.record(
        db, action="document.delete", user=user, resource_type="document", resource_id=document_id,
        detail={"filename": filename}, request=request,
    )
    return Response(status_code=204)
