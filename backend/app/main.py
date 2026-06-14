from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import redis.asyncio as aioredis

from app.api.v1 import chat, documents
from app.core.config import settings
from app.services.llm import LLMService, LLMServiceError
from app.utils.file_validator import FileValidationError
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
    redis_client: aioredis.Redis | None = None
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL.get_secret_value(),
            decode_responses=True,
        )
        await redis_client.ping()

        app.state.redis = redis_client
        app.state.llm_service = LLMService()
        app.state.rate_limiter = RateLimiterService(redis_client=redis_client)
    except Exception as exc:
        logger.critical(
            "Startup aborted — service initialization failed: %s", exc, exc_info=True
        )
        raise

    logger.info("Startup complete.")
    yield

    logger.info("Shutting down — releasing resources...")
    await app.state.rate_limiter.close()
    if redis_client is not None:
        await redis_client.aclose()
    logger.info("Shutdown complete.")

assert "*" not in settings.ALLOWED_ORIGINS, (
    "Wildcard origin ('*') is incompatible with allow_credentials=True. "
    "Set ALLOWED_ORIGINS to explicit origin(s) in your environment config."
)

app = FastAPI(
    title="Enterprise Multi-Tenant RAG API",
    description="Secure, isolated document ingestion and context-grounded LLM inference.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Tenant-ID"],
)

def _tenant_from(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", "unknown")

@app.exception_handler(FileValidationError)
async def file_validation_exception_handler(
    request: Request, exc: FileValidationError
) -> JSONResponse:
    logger.warning(
        "File validation rejected upload | tenant=%s path=%s error=%s",
        _tenant_from(request), request.url.path, exc,
    )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": str(exc),
            "error_code": "FILE_VALIDATION_FAILED",
        },
    )


@app.exception_handler(VectorStoreError)
async def vector_store_exception_handler(
    request: Request, exc: VectorStoreError
) -> JSONResponse:
    logger.error(
        "VectorStoreError | tenant=%s path=%s",
        _tenant_from(request), request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "detail": "A data storage or retrieval operation failed. Please try again later."
        },
    )


@app.exception_handler(LLMServiceError)
async def llm_service_exception_handler(
    request: Request, exc: LLMServiceError
) -> JSONResponse:
    logger.error(
        "LLMServiceError | tenant=%s path=%s",
        _tenant_from(request), request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "detail": "The inference provider failed to generate a response. Please try again later."
        },
    )


@app.exception_handler(RateLimitExceededError)
async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceededError
) -> JSONResponse:
    logger.warning(
        "Rate limit exceeded | tenant=%s path=%s",
        _tenant_from(request), request.url.path,
    )
    headers = {}
    if hasattr(exc, "retry_after_seconds") and exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers=headers,
        content={"detail": "Too many requests. Please back off and retry shortly."},
    )


@app.exception_handler(RateLimiterError)
async def rate_limiter_internal_handler(
    request: Request, exc: RateLimiterError
) -> JSONResponse:
    logger.error(
        "RateLimiterError | tenant=%s path=%s",
        _tenant_from(request), request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal infrastructure error occurred. Please try again later."
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    if isinstance(exc, RequestValidationError):
        raise exc

    logger.error(
        "Unhandled exception | tenant=%s method=%s path=%s",
        _tenant_from(request), request.method, request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal error occurred."},
    )

app.include_router(documents.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")

@app.get("/health", tags=["Telemetry"])
async def health_check(request: Request) -> JSONResponse:
    try:
        await request.app.state.redis.ping()
    except Exception:
        logger.error("Health check failed — Redis unreachable", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "redis": "unreachable"},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok", "redis": "ok"},
    )