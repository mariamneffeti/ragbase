from __future__ import annotations

import logging
import mimetypes
import os
from functools import lru_cache
from typing import Protocol

import anyio
from fastapi import UploadFile
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/x-markdown", ".md")
mimetypes.add_type("text/csv", ".csv")
mimetypes.add_type("text/plain", ".txt")
mimetypes.add_type("application/pdf", ".pdf")
mimetypes.add_type(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".docx",
)

_MB = 1024 * 1024

DEFAULT_MAX_SIZE = 10 * _MB
DEFAULT_ALLOWED_EXTENSIONS = frozenset({".txt", ".pdf", ".md", ".docx", ".csv"})
DEFAULT_ALLOWED_MIME_TYPES = frozenset({
    "text/plain",
    "application/pdf",
    "text/markdown",
    "text/x-markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/csv",
})

MIME_ALIASES: frozenset[frozenset[str]] = frozenset({
    frozenset({"text/markdown", "text/x-markdown"}),
})

MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
        b"PK\x03\x04",
    ],
}
MAGIC_READ_BYTES = 8

TEXT_MIME_PREFIX = "text/"

TEXT_SAFETY_READ_BYTES = 512


class _Seekable(Protocol):

    def seek(self, pos: int, whence: int = 0) -> int: ...
    def tell(self) -> int: ...


class FileValidatorSettings(BaseSettings):
    MAX_FILE_SIZE: int = DEFAULT_MAX_SIZE
    ALLOWED_EXTENSIONS: frozenset[str] = DEFAULT_ALLOWED_EXTENSIONS
    ALLOWED_MIME_TYPES: frozenset[str] = DEFAULT_ALLOWED_MIME_TYPES

    @field_validator("MAX_FILE_SIZE")
    @classmethod
    def max_size_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("MAX_FILE_SIZE must be a positive integer.")
        return v

    @model_validator(mode="after")
    def extensions_covered_by_mime_types(self) -> FileValidatorSettings:
        for ext in self.ALLOWED_EXTENSIONS:
            inferred, _ = mimetypes.guess_type(f"file{ext}")
            if inferred and inferred not in self.ALLOWED_MIME_TYPES:
                raise ValueError(
                    f"Extension '{ext}' infers MIME '{inferred}' which is not in "
                    "ALLOWED_MIME_TYPES. Add it or remove the extension."
                )
        return self

    model_config = {"env_prefix": "", "case_sensitive": True}


class FileValidationError(Exception):
    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class FileValidator:
    def __init__(self, config: FileValidatorSettings | None = None) -> None:
        cfg = config or FileValidatorSettings()
        self.max_file_size: int = cfg.MAX_FILE_SIZE
        self.allowed_extensions: frozenset[str] = cfg.ALLOWED_EXTENSIONS
        self.allowed_mime_types: frozenset[str] = cfg.ALLOWED_MIME_TYPES

    async def validate(self, file: UploadFile) -> None:
        file_size = 0
        try:
            self._validate_filename(file)
            self._validate_extension(file)
            self._validate_declared_mime(file)
            await self._validate_magic_bytes(file)
            await self._validate_text_safety(file)
            file_size = await self._measure_size(file)
            self._validate_size(file, file_size)

            logger.info(
                "File '%s' passed all validation checks (%d bytes, declared type: '%s').",
                file.filename,
                file_size,
                file.content_type,
            )
        finally:
            try:
                await file.seek(0)
            except Exception:
                logger.warning(
                    "Failed to rewind stream for '%s' after validation; "
                    "the caller will receive a partially-consumed file.",
                    file.filename,
                )

    def _validate_filename(self, file: UploadFile) -> None:
        if not file.filename or not file.filename.strip():
            raise FileValidationError("Uploaded file is missing a valid filename.")

    def _validate_extension(self, file: UploadFile) -> None:
        _, ext = os.path.splitext(file.filename.lower())  # type: ignore[arg-type]
        if ext not in self.allowed_extensions:
            logger.warning("Rejected upload — unsupported extension: '%s'.", ext)
            raise FileValidationError(
                message=f"Extension '{ext}' is not supported.",
                details={"allowed_extensions": sorted(self.allowed_extensions)},
            )

    def _validate_declared_mime(self, file: UploadFile) -> None:
        declared: str | None = file.content_type

        if not declared or declared not in self.allowed_mime_types:
            logger.warning("Rejected upload — disallowed MIME type: '%s'.", declared)
            raise FileValidationError(
                message=f"File type '{declared}' is not supported.",
                details={"allowed_types": sorted(self.allowed_mime_types)},
            )

        inferred, _ = mimetypes.guess_type(file.filename)  # type: ignore[arg-type]
        if inferred is None:
            logger.warning(
                "Rejected upload — MIME type could not be inferred from filename '%s'.",
                file.filename,
            )
            raise FileValidationError(
                message="Could not determine file type from filename.",
                details={"filename": file.filename},
            )

        if inferred not in self.allowed_mime_types:
            logger.warning(
                "Rejected upload — inferred MIME '%s' not in allowlist.", inferred
            )
            raise FileValidationError(
                message=f"File content type verification failed (inferred: '{inferred}').",
                details={"allowed_types": sorted(self.allowed_mime_types)},
            )

        if declared != inferred and not self._are_mime_aliases(declared, inferred):
            logger.warning(
                "Rejected upload — declared MIME '%s' does not match inferred '%s'.",
                declared,
                inferred,
            )
            raise FileValidationError(
                message="Declared Content-Type does not match the file extension.",
                details={"declared": declared, "inferred": inferred},
            )

    async def _validate_magic_bytes(self, file: UploadFile) -> None:
        signatures = MAGIC_SIGNATURES.get(file.content_type or "")
        if not signatures:
            return

        try:
            header = await file.read(MAGIC_READ_BYTES)
            await file.seek(0)
        except Exception as exc:
            raise FileValidationError(
                "Failed to read or rewind file stream during header verification."
            ) from exc

        if not any(header.startswith(sig) for sig in signatures):
            logger.warning(
                "Rejected upload '%s': magic bytes do not match declared type '%s'.",
                file.filename,
                file.content_type,
            )
            raise FileValidationError(
                message="File content does not match its declared type.",
                details={"declared_type": file.content_type},
            )

    async def _validate_text_safety(self, file: UploadFile) -> None:
        if not (file.content_type or "").startswith(TEXT_MIME_PREFIX):
            return

        try:
            sample = await file.read(TEXT_SAFETY_READ_BYTES)
            await file.seek(0)
        except Exception as exc:
            raise FileValidationError(
                "Failed to read or rewind file stream during text safety check."
            ) from exc

        if b"\x00" in sample:
            logger.warning(
                "Rejected upload '%s': null bytes found in text file.", file.filename
            )
            raise FileValidationError(
                message="Text file contains binary content (null bytes detected).",
                details={"declared_type": file.content_type},
            )

        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning(
                "Rejected upload '%s': content is not valid UTF-8.", file.filename
            )
            raise FileValidationError(
                message="Text file content is not valid UTF-8.",
                details={"declared_type": file.content_type},
            )

    async def _measure_size(self, file: UploadFile) -> int:
        def _seek_and_tell(file_obj: _Seekable) -> int:
            file_obj.seek(0, os.SEEK_END)
            size = file_obj.tell()
            file_obj.seek(0)
            return size

        try:
            return await anyio.to_thread.run_sync(_seek_and_tell, file.file)  
        except Exception as exc:
            logger.error("Could not determine size of '%s'.", file.filename)
            raise FileValidationError("Could not determine file size.") from exc

    def _validate_size(self, file: UploadFile, file_size: int) -> None:
        if file_size == 0:
            raise FileValidationError(
                message="Uploaded file is empty.",
                details={"filename": file.filename},
            )

        if file_size > self.max_file_size:
            max_mb = self.max_file_size / _MB
            actual_mb = file_size / _MB
            logger.warning(
                "Rejected upload '%s': %.2f MB exceeds limit of %.2f MB.",
                file.filename,
                actual_mb,
                max_mb,
            )
            raise FileValidationError(
                message=f"File size ({actual_mb:.1f} MB) exceeds the {max_mb:.1f} MB limit.",
                details={"max_bytes": self.max_file_size, "actual_bytes": file_size},
            )

    @staticmethod
    def _are_mime_aliases(a: str, b: str) -> bool:
        pair = frozenset({a, b})
        return any(pair <= alias_group for alias_group in MIME_ALIASES)

@lru_cache(maxsize=1)
def get_file_validator() -> FileValidator:
    return FileValidator()