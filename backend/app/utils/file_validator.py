from __future__ import annotations

import logging
import mimetypes
import os
from fastapi import UploadFile

from app.core.config import settings

logger = logging.getLogger(__name__)

mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/x-markdown", ".md")
mimetypes.add_type("text/csv", ".csv")
mimetypes.add_type("text/plain", ".txt")
mimetypes.add_type("application/pdf", ".pdf")
mimetypes.add_type(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 
    ".docx"
)

DEFAULT_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_ALLOWED_EXTENSIONS = {".txt", ".pdf", ".md", ".docx", ".csv"}
DEFAULT_ALLOWED_MIME_TYPES = {
    "text/plain",
    "application/pdf",
    "text/markdown",
    "text/x-markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/csv",
}


class FileValidationError(Exception):
    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class FileValidator:
    def __init__(self) -> None:
        self.max_file_size = getattr(settings, "MAX_FILE_SIZE", DEFAULT_MAX_SIZE)
        self.allowed_extensions = getattr(
            settings, "ALLOWED_EXTENSIONS", DEFAULT_ALLOWED_EXTENSIONS
        )
        self.allowed_mime_types = getattr(
            settings, "ALLOWED_MIME_TYPES", DEFAULT_ALLOWED_MIME_TYPES
        )

    async def validate(self, file: UploadFile) -> None:
        if not file.filename:
            raise FileValidationError("Uploaded file is missing a valid filename.")

        _, ext = os.path.splitext(file.filename.lower())
        if ext not in self.allowed_extensions:
            logger.warning("Rejected file upload: Extension '%s' not permitted.", ext)
            raise FileValidationError(
                message=f"Extension '{ext}' is not supported.",
                details={"allowed_extensions": list(self.allowed_extensions)},
            )

        content_type = file.content_type
        if content_type not in self.allowed_mime_types:
            logger.warning("Rejected file upload: MIME type '%s' is not allowed.", content_type)
            raise FileValidationError(
                message=f"File type '{content_type}' is not supported.",
                details={"allowed_types": list(self.allowed_mime_types)},
            )

        detected_mime, _ = mimetypes.guess_type(file.filename)
        if detected_mime and detected_mime not in self.allowed_mime_types:
            logger.warning(
                "Rejected file upload: Detected MIME '%s' does not match allowed types.",
                detected_mime,
            )
            raise FileValidationError(
                message=f"File content type verification failed for '{detected_mime}'.",
                details={"allowed_types": list(self.allowed_mime_types)},
            )

        try:
            file.file.seek(0, os.SEEK_END)
            file_size = file.file.tell()
            
            file.file.seek(0)
        except Exception as exc:
            logger.error("Failed to determine binary file stream size for '%s'", file.filename)
            raise FileValidationError("Could not determine file payload size metrics.") from exc

        if file_size > self.max_file_size:
            max_mb = self.max_file_size / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            logger.warning(
                "Rejected file upload '%s': Size %.2fMB exceeds limit of %.2fMB.",
                file.filename,
                actual_mb,
                max_mb,
            )
            raise FileValidationError(
                message=f"File exceeds maximum size threshold of {max_mb:.1f}MB.",
                details={"max_bytes": self.max_file_size, "actual_bytes": file_size},
            )

        logger.info(
            "File '%s' successfully passed validation metrics (%d bytes, verified type: '%s').",
            file.filename,
            file_size,
            content_type,
        )