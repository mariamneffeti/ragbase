from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.dependencies.auth import get_current_user, require_tenant_id
from app.services.llm import LLMService, LLMServiceError
from app.services.vector_store import VectorStoreService, VectorStoreError

logger = logging.getLogger(__name__)

_CONTEXT_TOP_K = 5

router = APIRouter(
    prefix="/chat",
    tags=["Conversational AI"],
)

class ChatQueryRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="The user prompt text.")


class ChatQueryResponse(BaseModel):
    answer: str = Field(..., description="The context-synthesized response from the LLM.")


@router.post("/query", response_model=ChatQueryResponse, status_code=status.HTTP_200_OK)
async def query_tenant_knowledge_base(
    payload: ChatQueryRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> ChatQueryResponse:
    tenant_id = require_tenant_id(current_user)
    rate_limiter = request.app.state.rate_limiter
    await rate_limiter.check_rate_limit(tenant_id, "chat:query", 100, 60)

    try:
        vector_store = VectorStoreService(tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning(
            "Invalid tenant context when constructing VectorStoreService for tenant '%s'",
            tenant_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tenant context.",
        ) from exc

    try:
        query_vector = await asyncio.to_thread(vector_store.embed_query, payload.message)
    except VectorStoreError as exc:
        logger.error(
            "Embedding generation failed for tenant '%s'",
            tenant_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream embedding service failure. Please retry shortly.",
        ) from exc

    try:
        context_matches = await asyncio.to_thread(
            vector_store.query_context,
            query_vector=query_vector,
            top_k=_CONTEXT_TOP_K,
        )
    except VectorStoreError as exc:
        logger.error(
            "Vector store query failed for tenant '%s'",
            tenant_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal search query could not be completed.",
        ) from exc

    llm_service: LLMService = request.app.state.llm_service
    try:
        answer = await llm_service.generate_rag_response(
            query=payload.message,
            context_matches=context_matches,
        )
    except LLMServiceError as exc:
        logger.error(
            "LLM response generation failed for tenant '%s'",
            tenant_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Response generation service temporarily unavailable.",
        ) from exc

    return ChatQueryResponse(answer=answer)