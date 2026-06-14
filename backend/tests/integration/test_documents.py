import io
import pytest
from unittest.mock import AsyncMock, patch
from app.main import app
from app.tasks.ingestion import DocumentIngestionService
from app.api.dependencies.auth import get_current_user
VALID_PDF = b"%PDF-1.4 " + b"A" * 512
CHAT_URL = "/api/v1/documents/upload"

@pytest.mark.asyncio
async def test_upload_valid_pdf_returns_202(client, mock_pinecone_index):
    with patch.object(DocumentIngestionService, "_extract_text", return_value="dummy extracted text"):
        response = await client.post(
            CHAT_URL,
            headers={"X-Tenant-ID": "tenant-1", "Authorization": "Bearer fake-token"},
            files={"file": ("report.pdf", io.BytesIO(VALID_PDF), "application/pdf")},
        )
    assert response.status_code == 202

@pytest.mark.asyncio
async def test_upload_invalid_file_returns_400(client,mock_pinecone_index):
    response = await client.post(
        CHAT_URL,
        headers={"X-Tenant-ID": "tenant-1", "Authorization": "Bearer fake-token"},
        files={"file": ("malware.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "FILE_VALIDATION_FAILED"

