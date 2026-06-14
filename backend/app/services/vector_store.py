from __future__ import annotations

import functools
import logging
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any, NotRequired, TypedDict

import anyio
import requests
from pinecone import Index, Pinecone

from app.core.config import settings

logger = logging.getLogger(__name__)

INDEX_NAME = "saas-rag-index"
PINECONE_INFERENCE_URL = "https://api.pinecone.io/embed"
EMBED_MODEL = "multilingual-e5-large"
EMBED_BATCH_SIZE = 96   # Hard limit for multilingual-e5-large
LIST_PAGE_SIZE = 99     # Pinecone list_paginated limit: 1–99


# ── Exceptions ────────────────────────────────────────────────────────

class VectorStoreError(Exception):
    pass


# ── TypedDicts ────────────────────────────────────────────────────────

class Vector(TypedDict):
    id: str
    values: list[float]
    metadata: NotRequired[dict[str, Any]]


class Match(TypedDict):
    id: str
    score: float
    values: list[float]
    metadata: NotRequired[dict[str, Any]]


# ── Pinecone inference ────────────────────────────────────────────────

def _inference_embed(texts: list[str], input_type: str) -> list[list[float]]:
    """
    Embed a list of texts via Pinecone's inference API.
    Automatically batches to respect the model's 96-input limit.
    """
    if not texts:
        return []

    api_key = settings.PINECONE_API_KEY.get_secret_value()
    headers = {
        "Api-Key": api_key,
        "Content-Type": "application/json",
        "X-Pinecone-API-Version": "2025-04",
    }

    all_embeddings: list[list[float]] = []

    for batch_start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[batch_start : batch_start + EMBED_BATCH_SIZE]
        payload = {
            "model": EMBED_MODEL,
            "inputs": [{"text": t} for t in batch],
            "parameters": {"input_type": input_type},
        }

        response = requests.post(
            PINECONE_INFERENCE_URL, json=payload, headers=headers, timeout=30
        )

        if not response.ok:
            logger.error(
                "Pinecone embed error (batch %d-%d, status %d): %s",
                batch_start,
                batch_start + len(batch) - 1,
                response.status_code,
                response.text,
            )

        response.raise_for_status()
        result = response.json()
        all_embeddings.extend(item["values"] for item in result["data"])

    return all_embeddings


# ── Singletons ────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_client() -> Pinecone:
    try:
        return Pinecone(api_key=settings.PINECONE_API_KEY.get_secret_value())
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


# ── Service ───────────────────────────────────────────────────────────

class VectorStoreService:
    def __init__(self, tenant_id: str) -> None:
        if not tenant_id or not tenant_id.strip():
            raise ValueError(
                "A non-empty tenant_id is required to instantiate VectorStoreService."
            )
        self.tenant_id = tenant_id
        self._index: Index = _get_index()

    # ── Embedding ─────────────────────────────────────────────────────

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("embed_query requires a non-empty text input.")
        try:
            return _inference_embed([text], "query")[0]
        except requests.RequestException as exc:
            logger.error("Query embed error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Embedding generation failed for tenant '{self.tenant_id}': {exc}"
            ) from exc

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            raise ValueError("embed_passages requires a non-empty list of texts.")
        try:
            return _inference_embed(texts, "passage")
        except requests.RequestException as exc:
            logger.error(
                "Passage embed error for tenant '%s': %s", self.tenant_id, exc
            )
            raise VectorStoreError(
                f"Passage embedding generation failed for tenant '{self.tenant_id}': {exc}"
            ) from exc

    # ── Upsert ────────────────────────────────────────────────────────

    def upsert_documents(self, vectors: list[Vector], batch_size: int = 100) -> None:
        if not vectors:
            logger.warning("upsert_documents called with an empty list — skipping.")
            return
        try:
            for i in range(0, len(vectors), batch_size):
                self._index.upsert(
                    vectors=vectors[i : i + batch_size],
                    namespace=self.tenant_id,
                )
            logger.info(
                "Upserted %d vector(s) for tenant '%s'.", len(vectors), self.tenant_id
            )
        except Exception as exc:
            logger.error("Upsert error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Failed to upsert vectors for tenant '{self.tenant_id}': {exc}"
            ) from exc

    async def upsert_document_chunks(
        self,
        document_id: str,
        chunks: list[str],
        metadata_template: dict[str, Any] | None = None,
    ) -> None:
        """Embed chunks and upsert them as vectors in a single pipeline call."""
        if not chunks:
            logger.warning(
                "upsert_document_chunks called with empty chunks for doc '%s'.",
                document_id,
            )
            return

        embeddings = await self.embed_passages_async(chunks)

        vectors: list[Vector] = [
            Vector(
                id=f"{document_id}#{i}",
                values=emb,
                metadata={
                    **(metadata_template or {}),
                    "document_id": document_id,
                    "chunk_index": i,
                    "text": chunks[i],  # required for RAG context retrieval
                },
            )
            for i, emb in enumerate(embeddings)
        ]

        await self.upsert_documents_async(vectors)

    # ── Query ─────────────────────────────────────────────────────────

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
            logger.error("Query error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Failed to query vectors for tenant '{self.tenant_id}': {exc}"
            ) from exc

    # ── Fetch / Delete ────────────────────────────────────────────────

    def fetch_ids_by_document(self, document_id: str) -> list[str]:
        if not document_id or not document_id.strip():
            raise ValueError("fetch_ids_by_document requires a non-empty document_id.")
        try:
            # index.list() is a generator that yields pages (each page is a list[str]).
            # We must flatten across pages rather than wrapping in list() directly.
            ids: list[str] = []
            for page in self._index.list(
                prefix=f"{document_id}#",
                namespace=self.tenant_id,
            ):
                if isinstance(page, list):
                    ids.extend(page)
                else:
                    ids.append(page)
            return ids
        except Exception as exc:
            logger.error(
                "Failed to fetch IDs for document '%s', tenant '%s': %s",
                document_id,
                self.tenant_id,
                exc,
            )
            raise VectorStoreError(
                f"Failed to fetch IDs for document '{document_id}': {exc}"
            ) from exc

    def delete_documents(self, vector_ids: list[str]) -> None:
        if not vector_ids:
            logger.warning("delete_documents called with an empty list — skipping.")
            return
        try:
            self._index.delete(ids=vector_ids, namespace=self.tenant_id)
            logger.info(
                "Deleted %d vector(s) for tenant '%s'.", len(vector_ids), self.tenant_id
            )
        except Exception as exc:
            logger.error("Delete error for tenant '%s': %s", self.tenant_id, exc)
            raise VectorStoreError(
                f"Failed to delete documents for tenant '{self.tenant_id}': {exc}"
            ) from exc

    def delete_by_document_id(self, document_id: str) -> None:
        if not document_id or not document_id.strip():
            raise ValueError("delete_by_document_id requires a non-empty document_id.")
        try:
            vector_ids = self.fetch_ids_by_document(document_id)
            if not vector_ids:
                logger.warning(
                    "No vectors found for document '%s', tenant '%s' — skipping delete.",
                    document_id,
                    self.tenant_id,
                )
                return
            self.delete_documents(vector_ids)
            logger.debug(
                "Deleted %d vectors for document '%s'.", len(vector_ids), document_id
            )
        except VectorStoreError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to delete document '%s', tenant '%s': %s",
                document_id,
                self.tenant_id,
                exc,
            )
            raise VectorStoreError(
                f"Failed to delete document '{document_id}' for tenant '{self.tenant_id}': {exc}"
            ) from exc

    def delete_all_user_data(self) -> None:
        try:
            self._index.delete(delete_all=True, namespace=self.tenant_id)
            logger.info("Deleted all vectors for tenant '%s'.", self.tenant_id)
        except Exception as exc:
            logger.error(
                "Failed to delete all data for tenant '%s': %s", self.tenant_id, exc
            )
            raise VectorStoreError(
                f"Failed to delete user data for tenant '{self.tenant_id}': {exc}"
            ) from exc

    # ── Listings ──────────────────────────────────────────────────────

    def list_all_vector_ids(self, page_size: int = LIST_PAGE_SIZE) -> list[str]:
        try:
            all_ids: list[str] = []
            pagination_token: str | None = None
            clamped = min(max(page_size, 1), LIST_PAGE_SIZE)

            while True:
                kwargs: dict[str, Any] = {
                    "namespace": self.tenant_id,
                    "limit": clamped,
                }
                if pagination_token:
                    kwargs["pagination_token"] = pagination_token

                response = self._index.list_paginated(**kwargs)
                all_ids.extend(v.id for v in (response.vectors or []))

                if response.pagination and response.pagination.next:
                    pagination_token = response.pagination.next
                else:
                    break

            return all_ids
        except Exception as exc:
            logger.error(
                "Failed to list vector IDs for tenant '%s': %s", self.tenant_id, exc
            )
            raise VectorStoreError(
                f"Failed to list vector IDs for tenant '{self.tenant_id}': {exc}"
            ) from exc

    async def list_document_ids_paginated(
        self, page_size: int = LIST_PAGE_SIZE
    ) -> AsyncGenerator[list[str], None]:
        """Async generator yielding pages of unique document IDs."""
        seen: set[str] = set()
        pagination_token: str | None = None
        clamped = min(max(page_size, 1), LIST_PAGE_SIZE)

        while True:
            def _fetch_page(token: str | None) -> tuple[list[str], str | None]:
                kwargs: dict[str, Any] = {
                    "namespace": self.tenant_id,
                    "limit": clamped,
                }
                if token:
                    kwargs["pagination_token"] = token
                resp = self._index.list_paginated(**kwargs)
                ids = [v.id for v in (resp.vectors or [])]
                next_token = resp.pagination.next if resp.pagination else None
                return ids, next_token

            raw_ids, next_token = await anyio.to_thread.run_sync(
                functools.partial(_fetch_page, pagination_token)
            )

            page: list[str] = []
            for vid in raw_ids:
                doc_id, _, _ = vid.partition("#")
                if doc_id and doc_id not in seen:
                    seen.add(doc_id)
                    page.append(doc_id)

            if page:
                yield page

            if not next_token:
                break
            pagination_token = next_token

    # ── Metadata ──────────────────────────────────────────────────────

    def get_metadata(self, vector_id: str) -> dict[str, Any] | None:
        try:
            response = self._index.fetch(ids=[vector_id], namespace=self.tenant_id)
            vectors = response.vectors
            if vector_id in vectors:
                return vectors[vector_id].metadata
            return None
        except Exception as exc:
            logger.error(
                "Failed to fetch metadata for vector '%s', tenant '%s': %s",
                vector_id,
                self.tenant_id,
                exc,
            )
            raise VectorStoreError(
                f"Failed to fetch metadata for vector '{vector_id}'"
            ) from exc

    # ── Async wrappers ────────────────────────────────────────────────

    async def embed_query_async(self, text: str) -> list[float]:
        return await anyio.to_thread.run_sync(self.embed_query, text)

    async def embed_passages_async(self, texts: list[str]) -> list[list[float]]:
        return await anyio.to_thread.run_sync(self.embed_passages, texts)

    async def upsert_documents_async(
        self, vectors: list[Vector], batch_size: int = 100
    ) -> None:
        await anyio.to_thread.run_sync(
            functools.partial(self.upsert_documents, vectors, batch_size)
        )

    async def query_context_async(
        self,
        query_vector: list[float],
        top_k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[Match]:
        return await anyio.to_thread.run_sync(
            functools.partial(self.query_context, query_vector, top_k, metadata_filter)
        )

    async def fetch_ids_by_document_async(self, document_id: str) -> list[str]:
        return await anyio.to_thread.run_sync(self.fetch_ids_by_document, document_id)

    async def delete_documents_async(self, vector_ids: list[str]) -> None:
        await anyio.to_thread.run_sync(self.delete_documents, vector_ids)

    async def delete_by_document_id_async(self, document_id: str) -> None:
        await anyio.to_thread.run_sync(self.delete_by_document_id, document_id)

    async def delete_all_user_data_async(self) -> None:
        await anyio.to_thread.run_sync(self.delete_all_user_data)

    async def get_metadata_async(self, vector_id: str) -> dict[str, Any] | None:
        return await anyio.to_thread.run_sync(self.get_metadata, vector_id)

    async def list_all_vector_ids_async(self, page_size: int = LIST_PAGE_SIZE) -> list[str]:
        return await anyio.to_thread.run_sync(
            functools.partial(self.list_all_vector_ids, page_size)
        )