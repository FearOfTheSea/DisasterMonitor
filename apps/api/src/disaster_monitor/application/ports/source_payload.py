"""Contracts for bounded source acquisition before immutable persistence."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AcquiredSourcePayload:
    """One bounded successful response prior to immutable persistence."""

    source_id: str
    canonical_request_identity: str
    provider_revision: str | None
    content: bytes
    content_type: str
    response_status: int
    retrieved_at: datetime
    published_at: datetime | None
    observed_at: datetime | None
    rights_id: str


class SourcePayloadAcquirer(Protocol):
    """Fetch one allowlisted request without deciding source authority."""

    async def acquire(
        self, canonical_request_identity: str
    ) -> AcquiredSourcePayload: ...


def canonical_request_identity(source_id: str, parameters: Mapping[str, str]) -> str:
    """Build a stable request identity without retaining credentials."""
    material = "&".join(
        f"{key}={parameters[key]}" for key in sorted(parameters) if parameters[key]
    )
    digest = hashlib.sha256(f"{source_id}|{material}".encode()).hexdigest()
    return f"request:{source_id}:{digest}"
