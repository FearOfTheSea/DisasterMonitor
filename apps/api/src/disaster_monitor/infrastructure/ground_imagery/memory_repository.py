"""Deterministic request metadata store used by local composition and tests."""

from disaster_monitor.application.ground_imagery.models import GroundImageryRequest
from disaster_monitor.application.ports.ground_imagery.selection_identity import (
    stable_selection_id,
)


class InMemoryGroundImageryRequestStore:
    """Small process-local store; durable deployments can replace this port."""

    durable = False

    def __init__(self) -> None:
        self.requests: dict[str, GroundImageryRequest] = {}

    async def get_request(self, request_id: str) -> GroundImageryRequest | None:
        return self.requests.get(request_id)

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
