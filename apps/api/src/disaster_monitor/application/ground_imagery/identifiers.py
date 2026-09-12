"""Stable identifiers and policy defaults for imagery artifacts."""

from __future__ import annotations

import hashlib
import json
import re

from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestInput,
)
from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid
from disaster_monitor.application.ports.ground_imagery.selection_identity import (
    stable_selection_id,
)
from disaster_monitor.domain.imagery.observations import (
    Observation,
    Sensor,
    TemporalRole,
)


def request_id(request_input: GroundImageryRequestInput) -> str:
    identity = {
        "owner_scope": request_input.owner_scope,
        "idempotency_key": request_input.idempotency_key,
    }
    if request_input.idempotency_key is None:
        identity.update(
            {
                "incident_id": request_input.incident_id,
                "reference_time": request_input.reference_time.isoformat(),
            }
        )
    payload = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"ground-imagery:{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def selection_id(
    request_id_value: str,
    sensor: Sensor,
    role: TemporalRole,
    observation: Observation,
) -> str:
    return stable_selection_id(
        request_id_value,
        sensor.value,
        role.value,
        observation.identity.stable_key,
    )


def default_recipe(sensor: Sensor) -> str:
    return (
        "s1-gamma0-terrain-v1" if sensor is Sensor.SENTINEL_1 else "s2-l2a-display-v1"
    )


def default_output_kind(sensor: Sensor) -> str:
    return (
        "s1-backscatter-display"
        if sensor is Sensor.SENTINEL_1
        else "s2-true-color-display"
    )


def artifact_id(
    request: GroundImageryRequest,
    selection: str,
    sensor: Sensor,
    role: TemporalRole,
    recipe_version: str,
    output_kind: str,
    grid: ImageryGrid,
) -> str:
    payload = json.dumps(
        {
            "request": request.request_id,
            "version": request.request_version,
            "region": request.region_resolution.region.geometry_hash
            if request.region_resolution.region is not None
            else None,
            "selection": selection,
            "sensor": sensor.value,
            "role": role.value,
            "recipe": recipe_version,
            "output": output_kind,
            "grid": {
                "crs": grid.crs,
                "bounds": [grid.min_x, grid.min_y, grid.max_x, grid.max_y],
                "pixel_size_m": grid.pixel_size_m,
                "width": grid.width,
                "height": grid.height,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"artifact:{hashlib.sha256(payload.encode()).hexdigest()[:48]}"


def unique_reasons(reasons: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


_SAFE_ARTIFACT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")


def validate_artifact_id(value: str) -> None:
    if not _SAFE_ARTIFACT_ID.fullmatch(value):
        raise ValueError("The imagery artifact ID is invalid.")


__all__ = [
    "artifact_id",
    "default_output_kind",
    "default_recipe",
    "request_id",
    "selection_id",
    "unique_reasons",
    "validate_artifact_id",
]
