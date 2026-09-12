"""Narrow request metadata persistence port."""

from typing import Protocol

from disaster_monitor.application.ground_imagery.models import GroundImageryRequest


class GroundImageryRequestStore(Protocol):
    async def get_request(self, request_id: str) -> GroundImageryRequest | None: ...

    async def get_request_for_selection(
        self, selection_id: str
    ) -> GroundImageryRequest | None: ...

    async def save_request(self, request: GroundImageryRequest) -> None: ...
