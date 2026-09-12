"""Credential-free provenance manifests for ground-imagery requests."""

from __future__ import annotations

from disaster_monitor.application.ground_imagery.identifiers import selection_id
from disaster_monitor.application.ground_imagery.models import GroundImageryRequest
from disaster_monitor.domain.imagery.observations import Observation


def build_manifest(request: GroundImageryRequest) -> dict[str, object]:
    """Build the stable, provider-credential-free request manifest."""
    region = request.region_resolution.region
    selected: list[dict[str, object]] = []
    if request.selection is not None:
        for sensor in request.requested_sensors:
            for outcome in request.selection.for_sensor(sensor).selections:
                if outcome.observation is not None:
                    selected.append(
                        {
                            "sensor": sensor.value,
                            "role": outcome.role.value,
                            "observation_id": outcome.observation.observation_id,
                            "selection_id": selection_id(
                                request.request_id,
                                sensor,
                                outcome.role,
                                outcome.observation,
                            ),
                            "reason": outcome.reason.value,
                        }
                    )
    return {
        "manifest_version": "ground-imagery-manifest-v1",
        "request_id": request.request_id,
        "request_version": request.request_version,
        "incident_id": request.incident_id,
        "disaster": request.disaster.value,
        "region": None
        if region is None
        else {
            "region_id": region.region_id,
            "version": region.version,
            "geometry_hash": region.geometry_hash,
            "core": region.core.as_geojson(),
            "inspection": region.inspection.as_geojson(),
            "association": region.association.value,
            "source_footprints": [
                {
                    "evidence_id": item.evidence_id,
                    "source_id": item.source.source_id,
                    "source_kind": item.source.source_kind.value,
                    "reference": item.source.reference,
                    "semantic_role": item.semantic_role,
                }
                for item in region.source_footprints
            ],
        },
        "temporal_policy_version": request.temporal_plan.policy_version,
        "reference_time": request.reference_time.isoformat(),
        "onset": None
        if request.temporal_plan.onset is None
        else {
            "earliest": request.temporal_plan.onset.earliest.isoformat(),
            "latest": request.temporal_plan.onset.latest.isoformat(),
            "source_id": request.temporal_plan.onset.source_id,
            "precision": request.temporal_plan.onset.precision,
        },
        "state": request.state.value,
        "reason_codes": list(request.reason_codes),
        "observations": [_observation_document(item) for item in request.candidates],
        "selections": selected,
        "artifacts": [
            {
                "artifact_id": item.artifact_id,
                "selection_id": item.selection_id,
                "sensor": item.sensor.value,
                "role": item.role.value,
                "output_kind": item.output_kind,
                "content_type": item.content_type,
                "storage_key": item.storage_key,
                "byte_count": item.byte_count,
                "sha256": item.sha256,
                "source_product_ids": list(item.source_product_ids),
                "grid": {
                    "crs": item.grid.crs,
                    "min_x": item.grid.min_x,
                    "min_y": item.grid.min_y,
                    "max_x": item.grid.max_x,
                    "max_y": item.grid.max_y,
                    "pixel_size_m": item.grid.pixel_size_m,
                    "width": item.grid.width,
                    "height": item.grid.height,
                    "resolution_label": item.grid.resolution_label,
                },
                "created_at": item.created_at.isoformat(),
            }
            for item in request.artifacts
        ],
    }


def request_has_selection(
    request: GroundImageryRequest, selection_id_value: str
) -> bool:
    if request.selection is None:
        return False
    return any(
        outcome.observation is not None
        and selection_id(request.request_id, sensor, outcome.role, outcome.observation)
        == selection_id_value
        for sensor in request.requested_sensors
        for outcome in request.selection.for_sensor(sensor).selections
    )


def _observation_document(observation: Observation) -> dict[str, object]:
    return {
        "observation_id": observation.observation_id,
        "sensor": observation.sensor.value,
        "product_id": observation.identity.product_id,
        "provider": observation.identity.provider,
        "revision": observation.identity.revision,
        "acquisition_id": observation.identity.acquisition_id,
        "datatake_id": observation.identity.datatake_id,
        "platform": observation.identity.platform,
        "processing_version": observation.identity.processing_version,
        "source_url": observation.identity.source_url,
        "captured_start": observation.capture.start.isoformat(),
        "captured_end": observation.capture.end.isoformat(),
        "readiness": observation.readiness.value,
        "footprint": observation.footprint.as_geojson(),
        "mode": observation.mode,
        "relative_orbit": observation.relative_orbit,
        "orbit_direction": observation.orbit_direction,
        "polarizations": list(observation.polarizations),
        "cloud_cover_fraction": observation.cloud_cover_fraction,
        "quality": None
        if observation.quality is None
        else {
            "covered_fraction": observation.quality.covered_fraction,
            "usable_fraction": observation.quality.usable_fraction,
            "obscured_fraction": observation.quality.obscured_fraction,
            "uncertain_fraction": observation.quality.uncertain_fraction,
            "uncovered_fraction": observation.quality.uncovered_fraction,
            "component_usable_fractions": dict(
                observation.quality.component_usable_fractions
            ),
            "quality_state": observation.quality.quality_state.value,
            "mask_definition": observation.quality.mask_definition,
        },
    }


__all__ = ["build_manifest", "request_has_selection"]
