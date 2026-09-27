"""Deterministic request metadata store used by local composition and tests."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

from disaster_monitor.application.ground_imagery.models import GroundImageryRequest
from disaster_monitor.application.ports.ground_imagery.selection_identity import (
    stable_selection_id,
)


class InMemoryGroundImageryRequestStore:
    """Small process-local store; durable deployments can replace this port."""

    durable = False

    def __init__(self) -> None:
        self.requests: dict[str, GroundImageryRequest] = {}
        self._watch_lock = asyncio.Lock()

    async def get_request(self, request_id: str) -> GroundImageryRequest | None:
        return self.requests.get(request_id)

    async def list_requests(self) -> tuple[GroundImageryRequest, ...]:
        return tuple(
            sorted(
                self.requests.values(),
                key=lambda item: (item.updated_at, item.request_id),
                reverse=True,
            )
        )

    async def get_request_for_selection(
        self, selection_id: str
    ) -> GroundImageryRequest | None:
        for request in self.requests.values():
            if any(
                artifact.selection_id == selection_id for artifact in request.artifacts
            ) or _request_has_selection(request, selection_id):
                return request
        return None

    async def save_request(self, request: GroundImageryRequest) -> None:
        current = self.requests.get(request.request_id)
        if current is None or request.request_version >= current.request_version:
            self.requests[request.request_id] = request

    async def claim_due_watch(self, *, now: datetime) -> str | None:
        async with self._watch_lock:
            due = sorted(
                (
                    request
                    for request in self.requests.values()
                    if request.watch_enabled
                    and request.next_check_at is not None
                    and request.next_check_at <= now
                    and request.watch_interval_seconds is not None
                ),
                key=lambda request: (request.next_check_at, request.request_id),
            )
            if not due:
                return None
            request = due[0]
            assert request.watch_interval_seconds is not None
            self.requests[request.request_id] = replace(
                request,
                next_check_at=now + timedelta(seconds=request.watch_interval_seconds),
                updated_at=now,
            )
            return request.request_id


def _request_has_selection(request: GroundImageryRequest, selection_key: str) -> bool:
    if request.selection is None:
        return False
    return any(
        outcome.observation is not None
        and stable_selection_id(
            request.request_id,
            sensor.value,
            outcome.role.value,
            outcome.observation.identity.stable_key,
        )
        == selection_key
        for sensor in request.requested_sensors
        for outcome in request.selection.for_sensor(sensor).selections
    )
