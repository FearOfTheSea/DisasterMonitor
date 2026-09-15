"""Operator-controlled AOI handoff packages for humanitarian mapping tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MappingWorkflowPackage:
    incident_id: str
    aoi_geojson: dict[str, Any]
    hot_tasking_manager_url: str
    mapswipe_url: str
    external_task_created: bool
    limitation: str


def build_mapping_workflow_package(
    *, incident_id: str, aoi: dict[str, Any]
) -> MappingWorkflowPackage:
    if not incident_id.strip():
        raise ValueError("Mapping workflow packages require an incident ID.")
    if aoi.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Mapping workflow handoff requires a polygonal AOI.")
    coordinates = aoi.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("Mapping workflow AOI coordinates are missing.")
    return MappingWorkflowPackage(
        incident_id=incident_id,
        aoi_geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": f"aoi:{incident_id}",
                    "geometry": aoi,
                    "properties": {
                        "incidentId": incident_id,
                        "authority": "operator_export",
                        "purpose": "mapping_workflow_handoff",
                    },
                }
            ],
        },
        hot_tasking_manager_url="https://tasks.hotosm.org/explore",
        mapswipe_url="https://mapswipe.org/en/get-involved/",
        external_task_created=False,
        limitation=(
            "This package only exports an operator-selected AOI. It does not create, "
            "embed, validate, or endorse an external mapping task."
        ),
    )
