from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.dependencies.auth import get_current_user
from app.main import app


@pytest.mark.asyncio
async def test_chat_rejects_unauthenticated_request(client):
    app.dependency_overrides.pop(get_current_user, None)
    try:
        response = await client.post("/api/v1/chat/query", json={"message": "hello"})
    finally:
        app.dependency_overrides[get_current_user] = async_tenant_a

    assert response.status_code == 401


async def async_tenant_a():
    return {"sub": "user-a", "tenant_id": "tenant-a"}


@pytest.mark.asyncio
async def test_tenant_a_list_cannot_read_tenant_b_documents(client):
    class TenantScopedStore:
        def __init__(self, tenant_id: str):
            self.tenant_id = tenant_id

        async def list_document_ids_paginated(self, page_size: int = 1000):
            yield ["document-a"] if self.tenant_id == "tenant-a" else ["document-b"]

        def fetch_ids_by_document(self, document_id: str):
            assert document_id == "document-a"
            return ["document-a#chunk_0"]

        async def get_metadata_async(self, vector_id: str):
            return {"title": "Tenant A document"}

    app.dependency_overrides[get_current_user] = async_tenant_a
    try:
        with patch("app.api.v1.documents.VectorStoreService", TenantScopedStore):
            response = await client.get("/api/v1/documents/list")
    finally:
        app.dependency_overrides[get_current_user] = async_tenant_a

    assert response.status_code == 200
    assert [document["document_id"] for document in response.json()] == ["document-a"]


@pytest.mark.asyncio
async def test_text_ingest_uses_mocked_vector_store(client):
    store = MagicMock()
    store.embed_passages.return_value = [[0.1] * 1024]

    with patch("app.api.v1.documents.VectorStoreService", return_value=store) as factory:
        response = await client.post(
            "/api/v1/documents/ingest/text",
            json={"title": "Team handbook", "content": "A useful test document."},
        )

    assert response.status_code == 201
    assert response.json()["chunks_processed"] == 1
    factory.assert_called_once_with(tenant_id="tenant-1")
    store.upsert_documents.assert_called_once()


@pytest.mark.asyncio
async def test_query_uses_mocked_vector_store_and_llm(client, mock_pinecone_index):
    store = MagicMock()
    store.embed_query.return_value = [0.1] * 1024
    store.query_context.return_value = [{"id": "chunk-a", "metadata": {"text": "Answer context"}}]

    with patch("app.api.v1.chat.VectorStoreService", return_value=store):
        response = await client.post(
            "/api/v1/chat/query", json={"message": "What does the document say?"}
        )

    assert response.status_code == 200
    assert response.json() == {"answer": "Hello world"}
    store.query_context.assert_called_once()
    app.state.llm_service.generate_rag_response.assert_awaited_once()
