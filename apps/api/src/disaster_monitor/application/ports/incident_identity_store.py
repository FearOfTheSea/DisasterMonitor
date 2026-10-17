"""Bounded local identity assignment persistence seam."""

from typing import Protocol


class IncidentIdentityStore(Protocol):
    def read(self) -> str | None: ...
    async def write(self, content: str) -> None: ...
