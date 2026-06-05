from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import redis.asyncio as aioredis                         
from app.api.v1 import chat, documents
from app.core.config import settings
from app.services.llm import LLMService, LLMServiceError
from app.core.rate_limiter import (                       
    RateLimitExceededError,
    RateLimiterError,
    RateLimiterService,
)
from app.services.vector_store import VectorStoreError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — initializing shared service singletons...")
    try:
        redis_client = aioredis.from_url(           
            settings.REDIS_URL,
            decode_responses=True,
        )
        app.state.llm_service = LLMService()
        app.state.rate_limiter = RateLimiterService(redis_client=redis_client)
    except ValueError as exc:
        logger.critical("Startup aborted — service initialization failed: %s", exc)
        raise

    logger.info("Startup complete.")
    yield
    logger.info("Shutting down — releasing resources...")
    await app.state.rate_limiter.close()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Enterprise Multi-Tenant RAG API",
    description="Secure, isolated document ingestion and context-grounded LLM inference.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)


_ALLOWED_ORIGINS: list[str] = settings.ALLOWED_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Tenant-ID"],
)


@app.exception_handler(VectorStoreError)
async def vector_store_exception_handler(request: Request, exc: VectorStoreError) -> JSONResponse:
    logger.error(
        "Unhandled VectorStoreError on %s %s",
        request.method,
        request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": "A data storage or retrieval operation failed. Please try again later."},
    )


@app.exception_handler(LLMServiceError)
async def llm_service_exception_handler(request: Request, exc: LLMServiceError) -> JSONResponse:
    logger.error(
        "Unhandled LLMServiceError on %s %s",
        request.method,
        request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": "The inference provider failed to generate a response. Please try again later."},
    )


@app.exception_handler(RateLimitExceededError)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceededError) -> JSONResponse:
    logger.warning(
        "Rate limit exceeded on %s %s",
        request.method,
        request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Too many requests. Please back off and retry shortly."},
    )


app.include_router(documents.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


@app.get("/health", tags=["Telemetry"], status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    return {"status": "ok"}