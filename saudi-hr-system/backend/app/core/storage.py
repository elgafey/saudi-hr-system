"""Private document storage abstraction (Phase 3).

Files live under ``{settings.storage_path}/private/employee_documents`` -
never inside the public frontend directory and never exposed as static URLs.
Bytes are only served through the authenticated, permission-checked
``GET /employees/{id}/documents/{doc_id}/download`` endpoint.

The storage_key stored in the database is server-generated (uuid4 + a
server-derived extension). Client-supplied file names are used for display
only and are never used to build a filesystem path, so path traversal from
user input is impossible by construction. Keys are re-validated on every
read as defense in depth.

Swapping this module for S3/Azure Blob/MinIO later only requires replacing
``FileStorage`` - the document model keeps storing an opaque ``storage_key``.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentEmptyFileError,
    DocumentFileTooLargeError,
    DocumentInvalidMimeTypeError,
    DocumentInvalidPathError,
    DocumentNotFoundError,
)

MAX_DOCUMENT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_DOCUMENT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/tiff",
    }
)

_EXT_BY_MIME: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
}

_KEY_PATTERN = re.compile(
    r"^company_\d+/employee_\d+/[0-9a-f]{32}\.[a-z0-9]{2,5}$"
)


def sniff_document_mime(data: bytes) -> str | None:
    """Detect the real content type from magic bytes (never trust metadata)."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "image/tiff"
    return None


def sanitize_filename(name: str) -> str:
    """Reduce a client file name to a safe display name (basename only)."""
    base = name.replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r'[\x00-\x1f\x7f"]', "", base).strip()
    return base[:255] or "file"


def validate_document_upload(
    *, filename: str, declared_mime: str | None, data: bytes
) -> tuple[str, str]:
    """Validate an upload. Returns ``(file_name, mime_type)``.

    Raises stable-coded DomainErrors for empty files, oversized files,
    disallowed MIME types and metadata spoofing (declared type that does
    not match the sniffed bytes).
    """
    if not data:
        raise DocumentEmptyFileError("Uploaded file is empty")
    if len(data) > MAX_DOCUMENT_FILE_SIZE:
        raise DocumentFileTooLargeError(
            f"File exceeds the {MAX_DOCUMENT_FILE_SIZE // (1024 * 1024)} MB limit"
        )
    sniffed = sniff_document_mime(data)
    if sniffed is None:
        raise DocumentInvalidMimeTypeError(
            "File content does not match any allowed document type"
        )
    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared and declared != sniffed:
        raise DocumentInvalidMimeTypeError(
            "Declared MIME type does not match file content"
        )
    if sniffed not in ALLOWED_DOCUMENT_MIME_TYPES:
        raise DocumentInvalidMimeTypeError(f"MIME type not allowed: {sniffed}")
    return sanitize_filename(filename), sniffed


class FileStorage:
    """Storage contract. Implementations must be safe against traversal."""

    def save(
        self, *, company_id: int, employee_id: int, data: bytes, mime_type: str
    ) -> str:
        raise NotImplementedError

    def load(self, storage_key: str) -> bytes:
        raise NotImplementedError

    def delete(self, storage_key: str) -> None:
        raise NotImplementedError


class LocalFileStorage(FileStorage):
    def __init__(self, root: Path | None = None) -> None:
        base = Path(root) if root is not None else Path(get_settings().storage_path)
        self.root = (base / "private" / "employee_documents").resolve()

    def save(
        self, *, company_id: int, employee_id: int, data: bytes, mime_type: str
    ) -> str:
        extension = _EXT_BY_MIME[mime_type]
        key = (
            f"company_{company_id}/employee_{employee_id}/"
            f"{uuid.uuid4().hex}{extension}"
        )
        target = self._resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def load(self, storage_key: str) -> bytes:
        target = self._resolve_key(storage_key)
        if not target.is_file():
            raise DocumentNotFoundError("Stored file is missing")
        return target.read_bytes()

    def delete(self, storage_key: str) -> None:
        target = self._resolve_key(storage_key)
        target.unlink(missing_ok=True)

    def _resolve_key(self, storage_key: str) -> Path:
        if not _KEY_PATTERN.fullmatch(storage_key):
            raise DocumentInvalidPathError("Invalid document storage path")
        target = (self.root / storage_key).resolve()
        if not target.is_relative_to(self.root):
            raise DocumentInvalidPathError("Invalid document storage path")
        return target


_storage: FileStorage | None = None


def get_storage() -> FileStorage:
    global _storage
    if _storage is None:
        _storage = LocalFileStorage()
    return _storage


def set_storage(storage: FileStorage | None) -> None:
    """Test hook: inject a fake storage backend."""
    global _storage
    _storage = storage
