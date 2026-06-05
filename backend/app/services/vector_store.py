from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, NotRequired, TypedDict

from pinecone import Pinecone, Index, exceptions as pinecone_exceptions

from app.core.config import settings

logger = logging.getLogger(__name__)

INDEX_NAME = "saas-rag-index"


class VectorStoreError(Exception):
    pass


@lru_cache(maxsize=1)
def _get_client() -> Pinecone:
    try:
        return Pinecone(api_key=settings.PINECONE_API_KEY)
    except Exception as exc:
        logger.error("Failed to initialise Pinecone client: %s", exc)
        raise VectorStoreError(f"Failed to initialise Pinecone client: {exc}") from exc


@lru_cache(maxsize=1)
def _get_index() -> Index:
    try:
        return _get_client().Index(INDEX_NAME)
    except Exception as exc:
        logger.error("Could not connect to Pinecone index '%s': %s", INDEX_NAME, exc)
        raise VectorStoreError(
            f"Could not connect to Pinecone index '{INDEX_NAME}': {exc}"
        ) from exc


class Vector(TypedDict):
    id: str
    values: list[float]
    metadata: NotRequired[dict[str, Any]]


class Match(TypedDict):
    id: str
    score: float
    values: list[float]
    metadata: NotRequired[dict[str, Any]]


class VectorStoreService:
    def __init__(self, tenant_id: str) -> None:
        if not tenant_id or not tenant_id.strip():
            raise ValueError(
                "A non-empty tenant_id is required to instantiate VectorStoreService."
            )
        self.tenant_id = tenant_id
        self._index: Index = _get_index()

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("embed_query requires a non-empty text input.")

        try:
            client = _get_client()
            response = client.inference.embed(
                model="multilingual-e5-large",
                inputs=[text],
                parameters={"input_type": "query"},
            )
            return response.data[0].values
        except pinecone_exceptions.PineconeException as exc:
            logger.error("Pinecone embedding error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Embedding generation failed for tenant '{self.tenant_id}': {exc}"
            ) from exc
        except Exception as exc:
            logger.error(
                "Unexpected error during embedding for tenant '%s': %s", self.tenant_id, exc
            )
            raise VectorStoreError(
                f"Unexpected embedding failure for tenant '{self.tenant_id}': {exc}"
            ) from exc
    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            raise ValueError("embed_passages requires a non-empty list of texts.")

        try:
            client = _get_client()
            response = client.inference.embed(
                model="multilingual-e5-large",
                inputs=texts,
                parameters={"input_type": "passage"},
            )
            return [item.values for item in response.data]
        except pinecone_exceptions.PineconeException as exc:
            logger.error("Pinecone passage embedding error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Passage embedding generation failed for tenant '{self.tenant_id}': {exc}"
            ) from exc
        except Exception as exc:
            logger.error(
                "Unexpected error during passage embedding for tenant '%s': %s", self.tenant_id, exc
            )
            raise VectorStoreError(
                f"Unexpected passage embedding failure for tenant '{self.tenant_id}': {exc}"
            ) from exc
    def upsert_documents(self, vectors: list[Vector], batch_size: int = 100) -> None:
        if not vectors:
            logger.warning("upsert_documents called with an empty list, nothing to do.")
            return

        try:
            for i in range(0, len(vectors), batch_size):
                chunk = vectors[i : i + batch_size]
                self._index.upsert(vectors=chunk, namespace=self.tenant_id)

            logger.info(
                "Upserted %d vector(s) for tenant '%s'.", len(vectors), self.tenant_id
            )

        except Exception as exc:
            logger.error("Pinecone upsert error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Failed to upsert vectors for tenant '{self.tenant_id}': {exc}"
            ) from exc

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
            logger.error("Pinecone query error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Failed to query vectors for tenant '{self.tenant_id}': {exc}"
            ) from exc
    def fetch_ids_by_document(self, document_id: str) -> list[str]:
        if not document_id or not document_id.strip():
            raise ValueError("fetch_ids_by_document requires a non-empty document_id.")

        try:
            response = self._index.query(
                namespace=self.tenant_id,
                vector=[0.0] * 1024,  # multilingual-e5-large is 1024-dim
                filter={"document_id": {"$eq": document_id}},
                top_k=10000,
                include_values=False,
            )
            return [match["id"] for match in response.matches]
        except Exception as exc:
            logger.error(
                "Failed to fetch vector IDs for document '%s', tenant '%s': %s",
                document_id, self.tenant_id, exc
            )
            raise VectorStoreError(
                f"Failed to fetch IDs for document '{document_id}': {exc}"
            ) from exc
    def delete_all_user_data(self) -> None:
        try:
            self._index.delete(delete_all=True, namespace=self.tenant_id)
            logger.info("Deleted all vectors for tenant '%s'.", self.tenant_id)
        except Exception as exc:
            logger.error("Pinecone delete error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Failed to delete user data for tenant '{self.tenant_id}': {exc}"
            ) from exc

    def delete_documents(self, vector_ids: list[str]) -> None:
        if not vector_ids:
            logger.warning("delete_documents called with an empty list, nothing to do.")
            return

        try:
            self._index.delete(ids=vector_ids, namespace=self.tenant_id)
            logger.info(
                "Deleted %d vector(s) for tenant '%s'.", len(vector_ids), self.tenant_id
            )
        except Exception as exc:
            logger.error("Pinecone delete error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Failed to delete documents for tenant '{self.tenant_id}': {exc}"
            ) from exc