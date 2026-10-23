"""Technical persistence contract for publisher robots rules and request timing."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PublicAccessReservation:
    token: str | None
    retry_after_seconds: float = 0


@dataclass(frozen=True, slots=True)
class PublicRedirectResume:
    destination: str
    visited: tuple[str, ...]


@dataclass(slots=True)
class PublicAccessDeferred(Exception):
    retry_after_seconds: float

    def __str__(self) -> str:
        return "Publisher robots request timing defers article retrieval."


class PublicDocumentAccess(Protocol):
    async def robots(self, host: str, *, now: float) -> str | None: ...

    async def remember_robots(
        self, host: str, text: str, interval: float, *, now: float
    ) -> None: ...

    async def claim(
        self, host: str, *, now: float, lease_seconds: float
    ) -> PublicAccessReservation: ...

    async def finish(self, host: str, token: str, *, now: float) -> None: ...

    async def redirect(
        self, url: str, *, now: float
    ) -> PublicRedirectResume | None: ...

    async def remember_redirect(
        self, url: str, resume: PublicRedirectResume, *, now: float
    ) -> None: ...

    async def clear_redirect(self, url: str) -> None: ...
