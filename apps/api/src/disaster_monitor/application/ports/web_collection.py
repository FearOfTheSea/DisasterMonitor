"""Consumer-owned persistence port for controlled web collection."""

from typing import Protocol

from disaster_monitor.domain.web_collection import WebFetchAudit, WebFetchState


class WebCollectionStore(Protocol):
    async def read_web_fetch_state(self, source_id: str) -> WebFetchState | None: ...

    async def save_web_fetch_state(self, state: WebFetchState) -> None: ...

    async def append_web_fetch_audit(self, audit: WebFetchAudit) -> bool: ...

    async def web_fetch_audits(
        self, *, source_id: str, limit: int = 100
    ) -> tuple[WebFetchAudit, ...]: ...
