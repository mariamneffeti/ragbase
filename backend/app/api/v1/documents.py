from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status,Request
from pydantic import BaseModel, Field, field_validator

from app.api.dependencies.auth import get_current_user
from app.services.vector_store import VectorStoreService, VectorStoreError, Vector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Knowledge Base Ingestion"])

_MAX_CONTENT_LENGTH = 200_000



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



def _get_tenant_id(current_user: dict) -> str:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing tenant ID.",
        )
    return tenant_id



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
    current_user: dict = Depends(get_current_user),
) -> IngestResponse:
    tenant_id = _get_tenant_id(current_user)
    rate_limiter = request.app.state.rate_limiter        
    await rate_limiter.check_rate_limit(tenant_id, "documents:ingest", 20, 60)
    try:
        vector_store = VectorStoreService(tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    request: Request, 
    current_user: dict = Depends(get_current_user),
) -> None:
    tenant_id = _get_tenant_id(current_user)
    rate_limiter = request.app.state.rate_limiter       
    await rate_limiter.check_rate_limit(tenant_id, "documents:delete", 30, 60)
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