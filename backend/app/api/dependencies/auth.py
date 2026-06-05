from __future__ import annotations

import asyncio
import logging
import time
import os

import jwt
import httpx
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings
from dotenv import load_dotenv
load_dotenv()
logger = logging.getLogger(__name__)

DISABLE_AUTH = os.getenv("DISABLE_AUTH", "false").lower() == "true"

if DISABLE_AUTH:
    logger.warning("⚠️  AUTH IS DISABLED — Swagger dev mode only, never deploy this way")

security = HTTPBearer(auto_error=False)

_jwks_cache: dict | None = None
_jwks_cache_time: float = 0.0
_JWKS_TTL = 3600
_jwks_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _jwks_lock
    if _jwks_lock is None:
        _jwks_lock = asyncio.Lock()
    return _jwks_lock


async def _get_supabase_public_keys() -> dict:
    global _jwks_cache, _jwks_cache_time
    if _jwks_cache and (time.time() - _jwks_cache_time) < _JWKS_TTL:
        return _jwks_cache
    async with _get_lock():
        if _jwks_cache and (time.time() - _jwks_cache_time) < _JWKS_TTL:
            return _jwks_cache
        jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(jwks_url, timeout=5)
                response.raise_for_status()
                _jwks_cache = response.json()
                _jwks_cache_time = time.time()
                return _jwks_cache
        except httpx.HTTPStatusError as exc:
            logger.error("Supabase JWKS endpoint returned a status error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication system could not fetch identity verification keys.",
            ) from exc
        except httpx.RequestError as exc:
            if _jwks_cache:
                logger.warning(
                    "JWKS refresh failed (network error); serving stale cache: %s", exc
                )
                return _jwks_cache
            logger.error(
                "Network error connecting to Supabase JWKS with no cache to fall back on: %s", exc
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication gateway temporarily unreachable.",
            ) from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> dict:
    if DISABLE_AUTH:
        return {
            "sub": "dev_user_123",
            "email": "admin@acme.corp",
            "tenant_id": "workspace_acme_prod",
        }

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials missing.",
        )

    token = credentials.credentials
    jwks = await _get_supabase_public_keys()

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise jwt.InvalidTokenError("Missing 'kid' in token header.")

        public_key_data = next(
            (key for key in jwks.get("keys", []) if key.get("kid") == kid), None
        )
        if not public_key_data:
            logger.warning(
                "Token 'kid' %r not found in JWKS — key may have been rotated. "
                "User should re-authenticate.",
                kid,
            )
            raise jwt.InvalidTokenError("Matching verification key not found in public JWKS.")

        public_key = jwt.PyJWK(public_key_data).key
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            leeway=10,
        )

        user_id = payload.get("sub")
        if not user_id:
            raise jwt.InvalidTokenError("Token payload missing identity subject (sub).")

        return {
            "tenant_id": str(user_id),
            "email": payload.get("email"),
            "supabase_role": payload.get("role"),
        }

    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please log in again.",
        ) from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("Rejected invalid authentication token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is invalid or structurally manipulated.",
        ) from exc


def require_tenant_id(current_user: dict) -> str:
    tenant_id = current_user.get("tenant_id")

    if not isinstance(tenant_id, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant identity could not be resolved from token.",
        )

    tenant_id = tenant_id.strip()

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant identity could not be resolved from token.",
        )

    return tenant_id