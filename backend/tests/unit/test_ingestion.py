from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tasks.ingestion import DocumentIngestionService, IngestionError


@pytest.mark.asyncio
async def test_file_upsert_failure_attempts_document_scoped_cleanup(upload_file_factory):
    vector_store = MagicMock()
    vector_store.tenant_id = "tenant-a"
    vector_store.upsert_document_chunks = AsyncMock(side_effect=RuntimeError("write failed"))
    vector_store.delete_by_document_id_async = AsyncMock()
    validator = MagicMock()
    validator.validate = AsyncMock()
    service = DocumentIngestionService(vector_store, validator=validator)

    with pytest.raises(IngestionError, match="Could not save document vectors"):
        await service.ingest_file(
            upload_file_factory("notes.txt", b"some valid document text", "text/plain"),
            document_id="doc-123",
        )

    vector_store.delete_by_document_id_async.assert_awaited_once_with("doc-123")


@pytest.mark.asyncio
async def test_file_ingestion_preserves_failure_if_cleanup_also_fails(upload_file_factory):
    vector_store = MagicMock()
    vector_store.tenant_id = "tenant-a"
    vector_store.upsert_document_chunks = AsyncMock(side_effect=RuntimeError("write failed"))
    vector_store.delete_by_document_id_async = AsyncMock(
        side_effect=RuntimeError("delete failed")
    )
    validator = MagicMock()
    validator.validate = AsyncMock()
    service = DocumentIngestionService(vector_store, validator=validator)

    with pytest.raises(IngestionError, match="Could not save document vectors"):
        await service.ingest_file(
            upload_file_factory("notes.txt", b"some valid document text", "text/plain"),
            document_id="doc-456",
        )

    vector_store.delete_by_document_id_async.assert_awaited_once_with("doc-456")
