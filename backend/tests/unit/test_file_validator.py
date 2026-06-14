import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock

from app.utils.file_validator import FileValidator, FileValidationError

PDF_MAGIC   = b"%PDF-1.4 " + b"A" * 512
PNG_MAGIC   = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
WRONG_BYTES = b"MZ\x90\x00"  


@pytest.mark.asyncio
async def test_valid_pdf_accepted(upload_file_factory):
    file = upload_file_factory("report.pdf", PDF_MAGIC, "application/pdf")
    await FileValidator().validate(file)  


@pytest.mark.asyncio
async def test_png_is_rejected(upload_file_factory):
    file = upload_file_factory("image.png", PNG_MAGIC, "image/png")
    with pytest.raises(FileValidationError):
        await FileValidator().validate(file)


@pytest.mark.asyncio
async def test_mismatched_extension_rejected(upload_file_factory):
    file = upload_file_factory("virus.exe", PDF_MAGIC, "application/pdf")
    with pytest.raises(FileValidationError, match=r"(?i)extension"):
        await FileValidator().validate(file)


@pytest.mark.asyncio
async def test_empty_file_rejected(upload_file_factory):
    file = upload_file_factory("empty.txt", b"", "text/plain")
    with pytest.raises(FileValidationError, match="empty"):
        await FileValidator().validate(file)


@pytest.mark.asyncio
async def test_oversized_file_rejected(upload_file_factory):
    file = upload_file_factory("big.txt", b"hello world", "text/plain")
    validator = FileValidator()
    validator._measure_size = AsyncMock(return_value=999_999_999)
    with pytest.raises(FileValidationError, match="size"):
        await validator.validate(file)