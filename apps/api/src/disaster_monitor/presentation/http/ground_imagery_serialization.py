"""Serialize ground imagery application records without leaking provider secrets."""

from __future__ import annotations

from typing import Any

from disaster_monitor.application.ground_imagery.identifiers import selection_id
from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    ImageryArtifactReference,
)
from disaster_monitor.application.ground_imagery.select_observations import (
    GroundImagerySelection,
)
from disaster_monitor.domain.imagery.observations import Observation, Sensor
from disaster_monitor.domain.imagery.regions import ImageryRegionVersion, RegionEvidence
from disaster_monitor.presentation.http.ground_imagery_schemas import (
    GroundImageryArtifactResponse,
    GroundImageryGridResponse,
    GroundImageryObservationPageResponse,
    GroundImageryObservationResponse,
    GroundImageryQualityResponse,
    GroundImageryRegionResolutionResponse,
    GroundImageryRegionResponse,
    GroundImageryRequestResponse,
    GroundImagerySelectionResponse,
    GroundImagerySensorStatusResponse,
    GroundImageryTemporalPlanResponse,
    GroundImageryTimeWindowResponse,
)


def ground_imagery_request_response(
    request: GroundImageryRequest,
) -> GroundImageryRequestResponse:
    region_resolution = request.region_resolution
    region = region_resolution.region
    selections = (
        {
            sensor: [
                _selection_response(request, sensor, outcome)
                for outcome in request.selection.for_sensor(sensor).selections
            ]
            for sensor in request.requested_sensors
            if request.selection is not None
        }
        if request.selection is not None
        else {}
    )
    sensor_statuses = []
    for status in request.search_status:
        sensor_statuses.append(
            GroundImagerySensorStatusResponse(
                sensor=status.sensor,
                scanned_count=status.scanned_count,
                scan_complete=status.scan_complete,
                next_cursor=status.next_cursor,
                failure_code=status.failure_code,
                failure_detail=status.failure_detail,
                selections=selections.get(status.sensor, []),
            )
        )
    return GroundImageryRequestResponse(
        request_id=request.request_id,
        request_version=request.request_version,
        incident_id=request.incident_id,
        disaster=request.disaster.value,
        state=request.state.value,
        reason_codes=list(request.reason_codes),
        reference_time=request.reference_time,
        region=GroundImageryRegionResolutionResponse(
            state=region_resolution.state.value,
            region=None if region is None else _region_response(region),
            alternatives=[
                _evidence_document(item) for item in region_resolution.alternatives
            ],
            warnings=list(region_resolution.warnings),
            reason_code=region_resolution.reason_code,
        ),
        temporal_plan=GroundImageryTemporalPlanResponse(
            policy_version=request.temporal_plan.policy_version,
            reference_time=request.temporal_plan.reference_time,
            impact_start_earliest=(
                request.temporal_plan.onset.earliest
                if request.temporal_plan.onset is not None
                else None
            ),
            impact_start_latest=(
                request.temporal_plan.onset.latest
                if request.temporal_plan.onset is not None
                else None
            ),
            onset_precision=(
                request.temporal_plan.onset.precision
                if request.temporal_plan.onset is not None
                else None
            ),
            onset_source_id=(
                request.temporal_plan.onset.source_id
                if request.temporal_plan.onset is not None
                else None
            ),
            windows=[
                GroundImageryTimeWindowResponse(
                    role=window.role.value,
                    sensor=window.sensor,
                    start=window.start,
                    end=window.end,
                    expanded_start=window.expanded_start,
                    expanded_end=window.expanded_end,
                )
                for window in request.temporal_plan.windows
            ],
        ),
        sensors=sensor_statuses,
        next_check_at=request.next_check_at,
        watch_enabled=request.watch_enabled,
        watch_interval_seconds=request.watch_interval_seconds,
        artifacts=[_artifact_response(item) for item in request.artifacts],
    )


def observation_response(observation: Observation) -> GroundImageryObservationResponse:
    quality = observation.quality
    return GroundImageryObservationResponse(
        observation_id=observation.observation_id,
        sensor=observation.sensor,
        product_id=observation.identity.product_id,
        acquisition_id=observation.identity.acquisition_id,
        revision=observation.identity.revision,
        platform=observation.identity.platform,
        captured_start=observation.capture.start,
        captured_end=observation.capture.end,
        readiness=observation.readiness.value,
        footprint=observation.footprint.as_geojson(),
        mode=observation.mode,
        relative_orbit=observation.relative_orbit,
        orbit_direction=observation.orbit_direction,
        polarizations=list(observation.polarizations),
        cloud_cover_fraction=observation.cloud_cover_fraction,
        source_url=observation.identity.source_url,
        quality=(
            None
            if quality is None
            else GroundImageryQualityResponse(
                covered_fraction=quality.covered_fraction,
                usable_fraction=quality.usable_fraction,
                obscured_fraction=quality.obscured_fraction,
                uncertain_fraction=quality.uncertain_fraction,
                uncovered_fraction=quality.uncovered_fraction,
                component_usable_fractions=dict(quality.component_usable_fractions),
                quality_state=quality.quality_state.value,
                mask_definition=quality.mask_definition,
            )
        ),
    )


def observation_page_response(
    observations: tuple[Observation, ...], next_cursor: str | None, total: int
) -> GroundImageryObservationPageResponse:
    return GroundImageryObservationPageResponse(
        observations=[observation_response(item) for item in observations],
        next_cursor=next_cursor,
        total=total,
    )


def _selection_response(
    request: GroundImageryRequest,
    sensor: Sensor,
    outcome: GroundImagerySelection,
) -> GroundImagerySelectionResponse:
    observation = outcome.observation
    return GroundImagerySelectionResponse(
        selection_id=(
            selection_id(request.request_id, sensor, outcome.role, observation)
            if observation is not None
            else f"selection:{request.request_id}:{sensor.value}:{outcome.role.value}"
        ),
        sensor=sensor,
        role=outcome.role.value,
        label=request.temporal_plan.label_for(outcome.role),
        observation=None if observation is None else observation_response(observation),
        reason=outcome.reason.value,
        explanation=outcome.explanation,
        age_class=outcome.age_class.value if outcome.age_class is not None else None,
        alternative_observation_ids=[
            item.observation_id for item in outcome.alternatives
        ],
    )


def _region_response(region: ImageryRegionVersion) -> GroundImageryRegionResponse:
    return GroundImageryRegionResponse(
        region_id=region.region_id,
        version=region.version,
        geometry_hash=region.geometry_hash,
        association=region.association.value,
        core=region.core.as_geojson(),
        inspection=region.inspection.as_geojson(),
        source_footprints=[
            _evidence_document(item) for item in region.source_footprints
        ],
    )


def _evidence_document(item: RegionEvidence) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "source_id": item.source.source_id,
        "source_kind": item.source.source_kind.value,
        "semantic_role": item.semantic_role,
        "association": item.association.value,
        "place_name": item.place_name,
        "country_code": item.country_code,
    }


def _artifact_response(
    artifact: ImageryArtifactReference,
) -> GroundImageryArtifactResponse:
    grid = artifact.grid
    return GroundImageryArtifactResponse(
        artifact_id=artifact.artifact_id,
        selection_id=artifact.selection_id,
        sensor=artifact.sensor,
        role=artifact.role.value,
        output_kind=artifact.output_kind,
        content_type=artifact.content_type,
        storage_key=artifact.storage_key,
        byte_count=artifact.byte_count,
        sha256=artifact.sha256,
        source_product_ids=list(artifact.source_product_ids),
        grid=GroundImageryGridResponse(
            crs=grid.crs,
            min_x=grid.min_x,
            min_y=grid.min_y,
            max_x=grid.max_x,
            max_y=grid.max_y,
            pixel_size_m=grid.pixel_size_m,
            width=grid.width,
            height=grid.height,
            resolution_label=grid.resolution_label,
        ),
        created_at=artifact.created_at,
    )
