from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import HTTPException, status
from pinecone import Pinecone, Index

from app.core.config import settings

logger = logging.getLogger(__name__)

INDEX_NAME = "saas-rag-index"


@lru_cache(maxsize=1)
def _get_client() -> Pinecone:
    try:
        return Pinecone(api_key=settings.PINECONE_API_KEY)
    except Exception as exc:
        logger.error("Failed to initialise Pinecone client: %s", exc)
        raise RuntimeError(f"Failed to initialise Pinecone client: {exc}") from exc


@lru_cache(maxsize=1)
def _get_index() -> Index:
    try:
        return _get_client().Index(INDEX_NAME)
    except Exception as exc:
        logger.error("Could not connect to Pinecone index '%s': %s", INDEX_NAME, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not connect to the vector storage index.",
        ) from exc


Vector = dict 
Match = dict   


class VectorStoreService:
    def __init__(self, tenant_id: str) -> None:
        if not tenant_id or not tenant_id.strip():
            raise ValueError(
                "A non-empty tenant_id is required to instantiate VectorStoreService."
            )
        self.tenant_id = tenant_id
        self._index: Index = _get_index()

    def upsert_documents(self, vectors: list[Vector], batch_size: int = 100) -> bool:
        if not vectors:
            logger.warning("upsert_documents called with an empty list, nothing to do.")
            return True

        try:
            for i in range(0, len(vectors), batch_size):
                chunk = vectors[i : i + batch_size]
                self._index.upsert(vectors=chunk, namespace=self.tenant_id)

            logger.info(
                "Upserted %d vector(s) for tenant '%s'.", len(vectors), self.tenant_id
            )
            return True

        except Exception as exc:
            logger.error(
                "Pinecone upsert error for tenant '%s': %s", self.tenant_id, exc
            )
            return False

    def query_context(
        self,
        query_vector: list[float],
        top_k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[Match]:
        if not query_vector:
            raise ValueError("query_vector must be a non-empty list of floats.")

        try:
            response = self._index.query(
                namespace=self.tenant_id,
                vector=query_vector,
                top_k=top_k,
                include_metadata=True,
                filter=metadata_filter,
            )
            return response.matches

        except Exception as exc:
            logger.error(
                "Pinecone query error for tenant '%s': %s", self.tenant_id, exc
            )
            return []

    def delete_all_user_data(self) -> None:
        try:
            self._index.delete(delete_all=True, namespace=self.tenant_id)
            logger.info(
                "Deleted all vectors for tenant '%s'.", self.tenant_id
            )
        except Exception as exc:
            logger.error(
                "Pinecone delete error for tenant '%s': %s", self.tenant_id, exc
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user data. Please try again.",
            ) from exc

    def delete_documents(self, vector_ids: list[str]) -> bool:
        if not vector_ids:
            logger.warning("delete_documents called with an empty list, nothing to do.")
            return True

        try:
            self._index.delete(ids=vector_ids, namespace=self.tenant_id)
            logger.info(
                "Deleted %d vector(s) for tenant '%s'.", len(vector_ids), self.tenant_id
            )
            return True
        except Exception as exc:
            logger.error(
                "Pinecone delete error for tenant '%s': %s", self.tenant_id, exc
            )
            return False