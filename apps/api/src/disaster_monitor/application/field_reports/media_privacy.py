"""Bounded privacy transformations applied before field media persistence."""

from __future__ import annotations

import re
import struct
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from disaster_monitor.domain.field_reports import FieldMediaLineage

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_METADATA_CHUNKS = {b"eXIf", b"iTXt", b"tEXt", b"zTXt"}
_SECRET_PATTERNS = (
    re.compile(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_PII_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)"),
)


class SensitiveFieldContentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SanitizedFieldMedia:
    content: bytes
    lineage: FieldMediaLineage


class FieldMediaPrivacyService:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        retention_days: int = 30,
        maximum_bytes: int = 8_000_000,
    ) -> None:
        if not 1 <= retention_days <= 365 or maximum_bytes <= 0:
            raise ValueError("Field-media privacy bounds are invalid.")
        self._clock = clock
        self._retention_days = retention_days
        self._maximum_bytes = maximum_bytes

    def validate_report_text(self, text: str) -> None:
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            raise SensitiveFieldContentError(
                "The report appears to contain a secret and was not persisted."
            )
        if any(pattern.search(text) for pattern in _PII_PATTERNS):
            raise SensitiveFieldContentError(
                "The report appears to contain direct contact PII and was not "
                "persisted."
            )

    def sanitize(
        self, *, filename: str, media_type: str, content: bytes
    ) -> SanitizedFieldMedia:
        if not content or len(content) > self._maximum_bytes:
            raise ValueError("Field media is empty or exceeds the byte limit.")
        self.validate_report_text(filename)
        if media_type == "image/jpeg":
            sanitized, removed = _strip_jpeg_app1(content)
            transformation = (
                "stripped-jpeg-app1-exif" if removed else "verified-no-jpeg-app1-exif"
            )
        elif media_type == "image/png":
            sanitized, removed = _strip_png_metadata(content)
            transformation = (
                "stripped-png-metadata" if removed else "verified-no-png-metadata"
            )
        else:
            raise ValueError("Field media is limited to JPEG and PNG images.")
        original_checksum = sha256(content).hexdigest()
        stored_checksum = sha256(sanitized).hexdigest()
        media_id = f"field-media:{stored_checksum}"
        lineage = FieldMediaLineage(
            media_id=media_id,
            original_filename=filename,
            media_type=media_type,
            original_sha256=original_checksum,
            stored_sha256=stored_checksum,
            byte_length=len(sanitized),
            transformations=(transformation, "bounded-retention-v1"),
            retention_expires_at=self._clock() + timedelta(days=self._retention_days),
        )
        return SanitizedFieldMedia(sanitized, lineage)


def _strip_jpeg_app1(content: bytes) -> tuple[bytes, bool]:
    if not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
        raise ValueError("Field JPEG content is malformed.")
    output = bytearray(content[:2])
    position = 2
    removed = False
    while position < len(content):
        if content[position] != 0xFF:
            output.extend(content[position:])
            break
        marker_start = position
        while position < len(content) and content[position] == 0xFF:
            position += 1
        if position >= len(content):
            raise ValueError("Field JPEG marker is truncated.")
        marker = content[position]
        position += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            output.extend(content[marker_start:position])
            if marker == 0xD9:
                if position != len(content):
                    raise ValueError("Field JPEG has trailing bytes.")
                break
            continue
        if position + 2 > len(content):
            raise ValueError("Field JPEG segment length is truncated.")
        segment_length = int.from_bytes(content[position : position + 2], "big")
        segment_end = position + segment_length
        if segment_length < 2 or segment_end > len(content):
            raise ValueError("Field JPEG segment is malformed.")
        if marker == 0xE1:
            removed = True
        else:
            output.extend(content[marker_start:segment_end])
        position = segment_end
        if marker == 0xDA:
            output.extend(content[position:])
            break
    return bytes(output), removed


def _strip_png_metadata(content: bytes) -> tuple[bytes, bool]:
    if not content.startswith(_PNG_SIGNATURE):
        raise ValueError("Field PNG content is malformed.")
    output = bytearray(_PNG_SIGNATURE)
    position = len(_PNG_SIGNATURE)
    removed = False
    saw_end = False
    while position < len(content):
        if position + 12 > len(content):
            raise ValueError("Field PNG chunk is truncated.")
        length = struct.unpack(">I", content[position : position + 4])[0]
        end = position + 12 + length
        if end > len(content):
            raise ValueError("Field PNG chunk is malformed.")
        chunk_type = content[position + 4 : position + 8]
        if chunk_type in _PNG_METADATA_CHUNKS:
            removed = True
        else:
            output.extend(content[position:end])
        position = end
        if chunk_type == b"IEND":
            saw_end = True
            break
    if not saw_end or position != len(content):
        raise ValueError("Field PNG must end with IEND and no trailing bytes.")
    return bytes(output), removed
