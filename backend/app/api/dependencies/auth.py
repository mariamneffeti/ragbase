from __future__ import annotations

import logging

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings

logger = logging.getLogger(__name__)

_ENV = settings.ENV.lower()
_bypass_requested = settings.DISABLE_AUTH
DISABLE_AUTH = _bypass_requested and _ENV in {"development", "test"}

if _bypass_requested and not DISABLE_AUTH:
    logger.error(
        "DISABLE_AUTH=true was set but ENV=%r is not a recognised dev/test "
        "environment — auth bypass is REFUSED. Set ENV=development explicitly.",
        _ENV,
    )

if DISABLE_AUTH:
    logger.warning(
        "AUTH IS DISABLED (ENV=%r) — dev mode only. "
        "Never deploy with ENV=development in production.",
        _ENV,
    )

_SUPABASE_URL = settings.SUPABASE_URL.get_secret_value().rstrip("/")
_JWKS_URL = f"{_SUPABASE_URL}/auth/v1/.well-known/jwks.json"
_EXPECTED_ISSUER = f"{_SUPABASE_URL}/auth/v1"
_JWT_LEEWAY_SECONDS = 10
_ALLOWED_ALGORITHMS = ["ES256", "RS256"]

_jwks_client = jwt.PyJWKClient(_JWKS_URL, cache_keys=True, lifespan=3600)

security = HTTPBearer(auto_error=False)

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> dict:
    if DISABLE_AUTH:
        return {
            "sub": "dev-user-local",
            "email": "dev@localhost",
            "tenant_id": "dev-tenant-local",
        }

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
        )

    token = credentials.credentials

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)

        unverified_header = jwt.get_unverified_header(token)
        token_alg = unverified_header.get("alg", "")
        key_alg = getattr(signing_key, "algorithm", None)
        if key_alg and token_alg != key_alg:
            logger.warning(
                "Token alg %r does not match JWK alg %r — rejecting.",
                token_alg,
                key_alg,
            )
            raise jwt.InvalidTokenError("Token algorithm inconsistent with signing key.")

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALLOWED_ALGORITHMS,
            audience="authenticated",
            issuer=_EXPECTED_ISSUER,
            leeway=_JWT_LEEWAY_SECONDS,
        )

        user_id = payload.get("sub")
        if not user_id:
            raise jwt.InvalidTokenError("Token payload missing identity subject (sub).")

        app_metadata = payload.get("app_metadata") or {}
        tenant_id = app_metadata.get("tenant_id") or str(user_id)

        return {
            "sub": str(user_id),
            "tenant_id": tenant_id,
            "email": payload.get("email"),
            "supabase_role": payload.get("role"),
        }

    except jwt.PyJWKClientConnectionError as exc:
        logger.warning("JWKS endpoint unreachable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication gateway temporarily unreachable.",
        ) from exc

    except jwt.ExpiredSignatureError:
        logger.info("Rejected expired token.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
        )

    except jwt.InvalidTokenError as exc:
        logger.warning("Rejected invalid token: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
        ) from exc


def require_tenant_id(
    current_user: dict = Depends(get_current_user),
) -> str:
    tenant_id = current_user.get("tenant_id", "").strip()
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
        )
    return tenant_id