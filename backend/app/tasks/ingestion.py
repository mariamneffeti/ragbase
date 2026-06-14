from __future__ import annotations

import csv
import functools
import io
import logging
from typing import TYPE_CHECKING, Any, TypedDict

import anyio
from fastapi import UploadFile

try:
    import pypdf
except ImportError:
    pypdf = None  

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None  

from app.utils.file_validator import FileValidationError, get_file_validator

if TYPE_CHECKING:
    from app.utils.file_validator import FileValidator
    from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)


class IngestionResult(TypedDict):
    document_id: str
    tenant_id: str
    total_chunks: int
    total_characters: int
    status: str


class IngestionError(Exception):
    pass


class DocumentIngestionService:
    def __init__(
        self,
        vector_store: VectorStoreService,
        validator: FileValidator | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size.")
        self.vector_store = vector_store
        self.validator = validator or get_file_validator()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def ingest_file(
        self,
        file: UploadFile,
        document_id: str,
    ) -> IngestionResult:
        await self.validator.validate(file)

        tenant_id = self.vector_store.tenant_id

        logger.info(
            "Starting ingestion pipeline | tenant=%s doc_id=%s filename=%s",
            tenant_id, document_id, file.filename,
        )

        try:
            content_bytes = await file.read()
            content_type = file.content_type or "text/plain"
            filename = file.filename

            raw_text: str = await anyio.to_thread.run_sync(
                functools.partial(self._extract_text, content_bytes, content_type, filename)
            )

            if not raw_text.strip():
                raise IngestionError("Document text extraction yielded empty content.")

            chunks: list[str] = await anyio.to_thread.run_sync(
                functools.partial(self._chunk_text, raw_text)
            )

            await self.vector_store.upsert_document_chunks(
                document_id=document_id,
                chunks=chunks,
                metadata_template={"filename": filename},
            )

            logger.info(
                "Ingestion complete | tenant=%s doc_id=%s chunks=%d chars=%d",
                tenant_id, document_id, len(chunks), len(raw_text),
            )

            return IngestionResult(
                document_id=document_id,
                tenant_id=tenant_id,
                total_chunks=len(chunks),
                total_characters=len(raw_text),
                status="success",
            )

        except FileValidationError:
            logger.warning(
                "File validation rejected '%s' for tenant '%s'", file.filename, tenant_id
            )
            raise
        except IngestionError:
            raise
        except Exception as exc:
            logger.error(
                "Pipeline failure | filename=%s tenant=%s error=%s",
                file.filename, tenant_id, exc,
                exc_info=True,
            )
            raise IngestionError(f"Ingestion pipeline failed: {exc}") from exc

    def _extract_text(
        self,
        content_bytes: bytes,
        content_type: str,
        filename: str | None,
    ) -> str:
        if content_type in ("text/plain", "text/markdown", "text/x-markdown"):
            return content_bytes.decode("utf-8", errors="replace")

        if content_type == "text/csv":
            return self._parse_csv(content_bytes)

        if content_type == "application/pdf":
            return self._parse_pdf(content_bytes)

        if content_type == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            return self._parse_docx(content_bytes)

        raise IngestionError(
            f"No configured parsing engine for MIME type: {content_type!r} "
            f"(file: {filename!r})"
        )

    def _parse_pdf(self, content_bytes: bytes) -> str:
        if pypdf is None:
            raise IngestionError("pypdf is not installed. Run: pip install pypdf")

        pages: list[str] = []
        with io.BytesIO(content_bytes) as stream:
            reader = pypdf.PdfReader(stream)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)

        return "\n\n".join(pages)

    def _parse_docx(self, content_bytes: bytes) -> str:
        if DocxDocument is None:
            raise IngestionError(
                "python-docx is not installed. Run: pip install python-docx"
            )

        with io.BytesIO(content_bytes) as stream:
            doc = DocxDocument(stream)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    def _parse_csv(self, content_bytes: bytes) -> str:
        decoded = content_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(decoded))
        rows = [
            f"Row {idx}: " + ", ".join(row)
            for idx, row in enumerate(reader)
            if any(field.strip() for field in row)
        ]
        return "\n".join(rows)

    def _chunk_text(self, text: str) -> list[str]:
        
        if len(text) <= self.chunk_size:
            return [text]

        stride = self.chunk_size - self.chunk_overlap
        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                lookback = min(100, end - start)
                tail = text[end - lookback : end]
                boundary = tail.rfind("\n")
                if boundary == -1:
                    boundary = tail.rfind(" ")
                if boundary != -1:
                    end = (end - lookback) + boundary + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start += stride

        return chunks