"""Process-local indexes for idempotent requests and stable selections."""

from __future__ import annotations

from disaster_monitor.application.ground_imagery.identifiers import selection_id
from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestInput,
)


class GroundImageryRequestIndexes:
    """Keep lookup state separate from the request orchestration policy."""

    def __init__(self) -> None:
        self._idempotency: dict[tuple[str, str], str] = {}
        self._selections: dict[str, str] = {}

    def request_for_idempotency(
        self, owner_scope: str, idempotency_key: str
    ) -> str | None:
        return self._idempotency.get((owner_scope, idempotency_key))

    def remember(
        self, request_input: GroundImageryRequestInput, request_id: str
    ) -> None:
        if request_input.idempotency_key is not None:
            self._idempotency[
                (request_input.owner_scope, request_input.idempotency_key)
            ] = request_id

    def index(self, request: GroundImageryRequest) -> None:
        if request.selection is None:
            return
        for sensor in request.requested_sensors:
            for outcome in request.selection.for_sensor(sensor).selections:
                if outcome.observation is not None:
                    self._selections[
                        selection_id(
                            request.request_id,
                            sensor,
                            outcome.role,
                            outcome.observation,
                        )
                    ] = request.request_id

    def request_for_selection(self, selection_id_value: str) -> str | None:
        return self._selections.get(selection_id_value)


__all__ = ["GroundImageryRequestIndexes"]
