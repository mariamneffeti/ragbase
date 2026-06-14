import pytest
from app.services.vector_store import VectorStoreService
from unittest.mock import patch, MagicMock
@pytest.fixture
def mock_pinecone_index():
    with patch("app.services.vector_store._get_index") as mock_get_index, \
         patch("app.services.vector_store._get_client") as mock_get_client:

        index = MagicMock()
        index.upsert = MagicMock()
        index.query = MagicMock(return_value=MagicMock(matches=[]))
        index.delete = MagicMock()
        index.list = MagicMock(return_value=[])  
        index.list_paginated = MagicMock(
            return_value=MagicMock(vectors=[], pagination=None)
        )
        mock_get_index.return_value = index

        client = MagicMock()
        fake_embedding = [0.1, 0.2, 0.3] 
        embed_response = MagicMock()
        embed_response.data = [MagicMock(values=fake_embedding) for _ in range(100)]
        client.inference.embed = MagicMock(return_value=embed_response)
        mock_get_client.return_value = client

        yield index

@pytest.mark.asyncio
async def test_upsert_calls_index_with_correct_namespace(mock_pinecone_index):
    svc = VectorStoreService(tenant_id="tenant-1")
    await svc.upsert_document_chunks(
        document_id="doc-abc",
        chunks=["chunk one", "chunk two"],
    )
    mock_pinecone_index.upsert.assert_called()
    _, kwargs = mock_pinecone_index.upsert.call_args
    assert kwargs.get("namespace") == "tenant-1"

@pytest.mark.asyncio
async def test_query_context_returns_empty(mock_pinecone_index):
    svc = VectorStoreService(tenant_id="tenant-1")
    dummy_vector = [0.0] * 1024
    results = await svc.query_context_async(dummy_vector, top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_delete_by_document_id_calls_index(mock_pinecone_index):
    mock_pinecone_index.list.return_value = ["doc-abc#0", "doc-abc#1"]
    svc = VectorStoreService(tenant_id="tenant-1")
    await svc.delete_by_document_id_async("doc-abc")
    mock_pinecone_index.delete.assert_called_once()


@pytest.mark.asyncio
async def test_different_tenants_use_different_namespaces(mock_pinecone_index):
    for tenant in ("tenant-1", "tenant-2"):
        svc = VectorStoreService(tenant_id=tenant)
        await svc.upsert_document_chunks(document_id="doc-x", chunks=["data"])

    calls = mock_pinecone_index.upsert.call_args_list
    namespaces = [c[1].get("namespace") for c in calls]
    assert "tenant-1" in namespaces
    assert "tenant-2" in namespaces
    assert namespaces[0] != namespaces[1]