from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status,Request,UploadFile 
from pydantic import BaseModel, Field, field_validator
from fastapi.responses import Response
from app.api.dependencies.auth import require_tenant_id
from app.services.vector_store import VectorStoreService, VectorStoreError, Vector
from app.core.rate_limiter import RateLimiterError
logger = logging.getLogger(__name__)
from app.tasks.ingestion import DocumentIngestionService, IngestionError
router = APIRouter(prefix="/documents", tags=["Knowledge Base Ingestion"])

_MAX_CONTENT_LENGTH = 200_000

class DocumentSummary(BaseModel):
    document_id: str
    title: str
    chunk_count: int
    filename: str | None = None


class IngestTextRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Title of the document.")
    content: str = Field(
        ...,
        min_length=10,
        max_length=_MAX_CONTENT_LENGTH,
        description="The raw text content to index.",
    )

    @field_validator("title")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        return v.strip().replace('"', "").replace("'", "").replace("\\", "")


class IngestResponse(BaseModel):
    status: str = "success"
    document_id: str
    chunks_processed: int

def split_into_chunks(text: str, chunk_size: int = 250, overlap: int = 50) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError(
            f"overlap ({overlap}) must be strictly less than chunk_size ({chunk_size})."
        )

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    step = chunk_size - overlap
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        i += step
    return chunks

@router.post("/ingest/text", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_raw_text(
    payload: IngestTextRequest,
    request: Request,
    tenant_id: str = Depends(require_tenant_id),
) -> IngestResponse:
    rate_limiter = request.app.state.rate_limiter 
    try:
        await rate_limiter.check_rate_limit(tenant_id, "documents:ingest", 20, 60)
    except RateLimiterError as exc:  
        logger.error("Rate limiter failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable.",
        )       
    try:
        vector_store = VectorStoreService(tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning("Invalid request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request parameters.",
        ) from exc

    try:
        chunks = split_into_chunks(payload.content, chunk_size=250, overlap=50)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content could not be parsed into chunks.",
        )

    document_id = str(uuid.uuid4())

    try:
        embeddings = await asyncio.to_thread(vector_store.embed_passages, chunks)
    except VectorStoreError as exc:
        logger.error(
            "Embedding generation failed during ingestion for tenant '%s'",
            tenant_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate embeddings via upstream provider.",
        ) from exc

    if len(embeddings) != len(chunks):
        logger.error(
            "Embedding count mismatch for tenant '%s': expected %d, got %d",
            tenant_id,
            len(chunks),
            len(embeddings),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Embedding provider returned an unexpected number of results.",
        )

    vectors_to_upsert: list[Vector] = [
        {
            "id": f"{document_id}#chunk_{i}",
            "values": embedding,
            "metadata": {
                "document_id": document_id,
                "title": payload.title,
                "text": chunk,
                "chunk_index": i,
            },
        }
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    try:
        await asyncio.to_thread(vector_store.upsert_documents, vectors_to_upsert, 100)
    except VectorStoreError as exc:
        logger.error(
            "Upsert failed for tenant '%s'",
            tenant_id,
            exc_info=True,
        )
        _chunk_ids = [v["id"] for v in vectors_to_upsert]
        try:
            await asyncio.to_thread(vector_store.delete_documents, _chunk_ids)
        except VectorStoreError:
            logger.error(
                "Rollback also failed for tenant '%s', document '%s' — manual cleanup may be required",
                tenant_id,
                document_id,
                exc_info=True,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save document into the knowledge base.",
        ) from exc

    return IngestResponse(document_id=document_id, chunks_processed=len(vectors_to_upsert))
@router.get("/list", response_model=list[DocumentSummary])
async def list_documents(
    tenant_id: str = Depends(require_tenant_id),
) -> list[DocumentSummary]:
        try:
            vector_store = VectorStoreService(tenant_id=tenant_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tenant context.",
            ) from exc

        summaries: list[DocumentSummary] = []
        try:
            # 1. Get all distinct document IDs (streaming, memory‑safe)
            doc_ids: list[str] = []
            async for page in vector_store.list_document_ids_paginated(page_size=1_000):
                doc_ids.extend(page)

            # 2. For each document, fetch the first chunk's metadata (title/filename)
            #    and count the total number of chunks.
            #    We limit concurrency to avoid overwhelming Pinecone.
            sem = asyncio.Semaphore(10)   # max 10 concurrent fetches

            async def build_summary(doc_id: str) -> DocumentSummary:
                async with sem:
                    # Get all chunk IDs for this document
                    chunk_ids = await asyncio.to_thread(
                        vector_store.fetch_ids_by_document, doc_id
                    )
                    chunk_count = len(chunk_ids)

                    # Get metadata from the first chunk (fallback if missing)
                    title = doc_id   # default fallback
                    filename = None
                    if chunk_ids:
                        first_chunk_id = chunk_ids[0]
                        try:
                            metadata = await vector_store.get_metadata_async(first_chunk_id)
                            if metadata:
                                title = metadata.get("title", title)
                                filename = metadata.get("filename")
                        except VectorStoreError:
                            logger.warning(
                                "Could not fetch metadata for chunk '%s', using doc_id as title.",
                                first_chunk_id,
                            )

                    return DocumentSummary(
                        document_id=doc_id,
                        title=title,
                        chunk_count=chunk_count,
                        filename=filename,
                    )

            tasks = [build_summary(doc_id) for doc_id in doc_ids]
            summaries = await asyncio.gather(*tasks)

        except VectorStoreError as exc:
            logger.error(
                "Failed to list documents for tenant '%s': %s",
                tenant_id, exc,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to retrieve document list from knowledge base.",
            ) from exc

        return summaries

@router.post("/upload", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def upload_document(
    file: UploadFile,
    request: Request,
    tenant_id: str = Depends(require_tenant_id),
):
    vector_store = VectorStoreService(tenant_id=tenant_id)
    ingestion = DocumentIngestionService(vector_store=vector_store)
    result = await ingestion.ingest_file(file, document_id=str(uuid.uuid4()))
    return result

@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    request: Request, 
    tenant_id: str = Depends(require_tenant_id),
) -> Response:
    rate_limiter = request.app.state.rate_limiter  
    try:
        await rate_limiter.check_rate_limit(tenant_id, "documents:delete", 30, 60)
    except RateLimiterError as exc:  
        logger.error("Rate limiter failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable.",
        )          
    try:
        vector_store = VectorStoreService(tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        chunk_ids = await asyncio.to_thread(
            vector_store.fetch_ids_by_document, str(document_id)
        )
    except VectorStoreError as exc:
        logger.error(
            "Failed to look up chunk IDs for document '%s', tenant '%s'",
            document_id,
            tenant_id,
            exc_info=True,  
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve document chunks for deletion.",
        ) from exc
    if not chunk_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No document found with ID '{document_id}'.",
        )
    try:
        await asyncio.to_thread(vector_store.delete_documents, chunk_ids)
    except VectorStoreError as exc:
        logger.error(
            "Deletion failed for document '%s', tenant '%s'",
            document_id,
            tenant_id,
            exc_info=True,  
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document from the knowledge base.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)