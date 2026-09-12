"""JSON-safe codec for the durable ground-imagery request boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestState,
    SensorSearchStatus,
)
from disaster_monitor.application.ground_imagery.resolve_region import (
    RegionResolution,
    RegionResolutionState,
)
from disaster_monitor.application.ground_imagery.select_observations import (
    GroundImagerySelection,
    SelectionReason,
    SelectionResult,
    SensorSelection,
)
from disaster_monitor.application.ground_imagery.temporal_policy import (
    RoleWindow,
    TemporalPlan,
)
from disaster_monitor.application.ports.ground_imagery import (
    repository_codec_artifacts as _codec_artifacts,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    age_class as _age_class,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    datetime_value as _datetime,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    integer as _integer,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    list_value as _list,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    mapping as _mapping,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    mapping_value as _mapping_value,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    number as _number,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    number_item as _number_item,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    optional_datetime as _optional_datetime,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    optional_string as _optional_string,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    parse_datetime as _parse_datetime_value,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    string as _string,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    string_first as _string_first,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    string_pair as _string_pair,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    string_value as _string_value,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationQuality,
    ObservationReadiness,
    OnsetPrecision,
    QualityState,
    Sensor,
    TemporalRole,
)
from disaster_monitor.domain.imagery.observations import (
    ImpactOnset as DomainImpactOnset,
)
from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    ImageryRegionVersion,
    RegionEvidence,
    RegionRole,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)


def request_to_document(request: GroundImageryRequest) -> dict[str, Any]:
    """Encode a request without provider credentials or signed URLs."""
    return {
        "request_id": request.request_id,
        "request_version": request.request_version,
        "incident_id": request.incident_id,
        "disaster": request.disaster.value,
        "reference_time": request.reference_time.isoformat(),
        "requested_sensors": [sensor.value for sensor in request.requested_sensors],
        "region_resolution": _region_resolution_document(request.region_resolution),
        "temporal_plan": _temporal_plan_document(request.temporal_plan),
        "candidates": [_observation_document(item) for item in request.candidates],
        "search_status": [
            {
                "sensor": item.sensor.value,
                "scanned_count": item.scanned_count,
                "scan_complete": item.scan_complete,
                "next_cursor": item.next_cursor,
                "failure_code": item.failure_code,
                "failure_detail": item.failure_detail,
            }
            for item in request.search_status
        ],
        "selection": _selection_document(request.selection),
        "state": request.state.value,
        "reason_codes": list(request.reason_codes),
        "created_at": request.created_at.isoformat(),
        "updated_at": request.updated_at.isoformat(),
        "owner_scope": request.owner_scope,
        "watch_enabled": request.watch_enabled,
        "watch_interval_seconds": request.watch_interval_seconds,
        "next_check_at": (
            None if request.next_check_at is None else request.next_check_at.isoformat()
        ),
        "artifacts": [
            _codec_artifacts.artifact_document(item) for item in request.artifacts
        ],
    }


def request_from_document(document: Mapping[str, Any]) -> GroundImageryRequest:
    """Decode a previously validated request document.

    A corrupt or partially migrated document raises ``ValueError`` so the
    repository can report a durable metadata failure instead of returning a
    misleading partial request.
    """
    region_resolution = _region_resolution_from_document(
        _mapping(document, "region_resolution")
    )
    temporal_plan = _temporal_plan_from_document(_mapping(document, "temporal_plan"))
    candidates = tuple(
        _observation_from_document(item) for item in _list(document, "candidates")
    )
    by_id = {item.observation_id: item for item in candidates}
    selection = _selection_from_document(
        document.get("selection"), temporal_plan, by_id
    )
    return GroundImageryRequest(
        request_id=_string(document, "request_id"),
        request_version=_integer(document, "request_version"),
        incident_id=_string(document, "incident_id"),
        disaster=Disaster(_string(document, "disaster")),
        reference_time=_datetime(document, "reference_time"),
        requested_sensors=tuple(
            Sensor(value) for value in _list(document, "requested_sensors")
        ),
        region_resolution=region_resolution,
        temporal_plan=temporal_plan,
        candidates=candidates,
        search_status=tuple(
            _search_status_from_document(item)
            for item in _list(document, "search_status")
        ),
        selection=selection,
        state=GroundImageryRequestState(_string(document, "state")),
        reason_codes=tuple(
            _string_value(item, "reason_codes")
            for item in _list(document, "reason_codes")
        ),
        created_at=_datetime(document, "created_at"),
        updated_at=_datetime(document, "updated_at"),
        owner_scope=_string(document, "owner_scope"),
        watch_enabled=bool(document.get("watch_enabled", False)),
        watch_interval_seconds=(
            None
            if document.get("watch_interval_seconds") is None
            else _integer(document, "watch_interval_seconds")
        ),
        next_check_at=(
            None
            if document.get("next_check_at") is None
            else _datetime(document, "next_check_at")
        ),
        artifacts=tuple(
            _codec_artifacts.artifact_from_document(item)
            for item in (
                _list(document, "artifacts") if "artifacts" in document else []
            )
        ),
    )


def _region_resolution_document(resolution: RegionResolution) -> dict[str, Any]:
    return {
        "state": resolution.state.value,
        "region": (
            None if resolution.region is None else _region_document(resolution.region)
        ),
        "alternatives": [_evidence_document(item) for item in resolution.alternatives],
        "warnings": list(resolution.warnings),
        "reason_code": resolution.reason_code,
    }


def _region_resolution_from_document(
    document: Mapping[str, Any],
) -> RegionResolution:
    region_document = document.get("region")
    return RegionResolution(
        state=RegionResolutionState(_string(document, "state")),
        region=(
            None
            if region_document is None
            else _region_from_document(_mapping_value(region_document))
        ),
        alternatives=tuple(
            _evidence_from_document(item) for item in _list(document, "alternatives")
        ),
        warnings=tuple(
            _string_value(item, "warnings") for item in _list(document, "warnings")
        ),
        reason_code=(
            None
            if document.get("reason_code") is None
            else _string(document, "reason_code")
        ),
    )


def _region_document(region: ImageryRegionVersion) -> dict[str, Any]:
    return {
        "region_id": region.region_id,
        "version": region.version,
        "core": region.core.as_geojson(),
        "inspection": region.inspection.as_geojson(),
        "source_footprints": [
            _evidence_document(item) for item in region.source_footprints
        ],
        "core_role": region.core_role.value,
        "inspection_role": region.inspection_role.value,
        "association": region.association.value,
        "parent_region_id": region.parent_region_id,
        "derivation_inputs": list(region.derivation_inputs),
        "display_geometry": (
            None
            if region.display_geometry is None
            else region.display_geometry.as_geojson()
        ),
    }


def _region_from_document(document: Mapping[str, Any]) -> ImageryRegionVersion:
    display = document.get("display_geometry")
    return ImageryRegionVersion(
        region_id=_string(document, "region_id"),
        version=_integer(document, "version"),
        core=polygon_from_geojson(_mapping(document, "core")),
        inspection=polygon_from_geojson(_mapping(document, "inspection")),
        source_footprints=tuple(
            _evidence_from_document(item)
            for item in _list(document, "source_footprints")
        ),
        core_role=RegionRole(_string(document, "core_role")),
        inspection_role=RegionRole(_string(document, "inspection_role")),
        association=AssociationStatus(_string(document, "association")),
        parent_region_id=(
            None
            if document.get("parent_region_id") is None
            else _string(document, "parent_region_id")
        ),
        derivation_inputs=tuple(
            _string_value(item, "derivation_inputs")
            for item in _list(document, "derivation_inputs")
        ),
        display_geometry=(
            None if display is None else polygon_from_geojson(_mapping_value(display))
        ),
    )


def _evidence_document(evidence: RegionEvidence) -> dict[str, Any]:
    return {
        "evidence_id": evidence.evidence_id,
        "geometry": (
            None if evidence.geometry is None else evidence.geometry.as_geojson()
        ),
        "source": {
            "source_id": evidence.source.source_id,
            "source_kind": evidence.source.source_kind.value,
            "publisher": evidence.source.publisher,
            "reference": evidence.source.reference,
            "source_crs": evidence.source.source_crs,
            "captured_at": (
                None
                if evidence.source.captured_at is None
                else evidence.source.captured_at.isoformat()
            ),
            "represented_year": evidence.source.represented_year,
            "attribution": evidence.source.attribution,
            "metadata": [list(item) for item in evidence.source.metadata],
        },
        "association": evidence.association.value,
        "semantic_role": evidence.semantic_role,
        "component_id": evidence.component_id,
        "place_name": evidence.place_name,
        "country_code": evidence.country_code,
        "observed_at": (
            None if evidence.observed_at is None else evidence.observed_at.isoformat()
        ),
        "derivation_inputs": list(evidence.derivation_inputs),
    }


def _evidence_from_document(document: object) -> RegionEvidence:
    value = _mapping_value(document)
    source = _mapping(value, "source")
    geometry = value.get("geometry")
    captured_at = source.get("captured_at")
    observed_at = value.get("observed_at")
    return RegionEvidence(
        evidence_id=_string(value, "evidence_id"),
        geometry=(
            None if geometry is None else polygon_from_geojson(_mapping_value(geometry))
        ),
        source=RegionSource(
            source_id=_string(source, "source_id"),
            source_kind=RegionSourceKind(_string(source, "source_kind")),
            publisher=_string(source, "publisher"),
            reference=_string(source, "reference"),
            source_crs=_string(source, "source_crs"),
            captured_at=(
                None if captured_at is None else _parse_datetime_value(captured_at)
            ),
            represented_year=(
                None
                if source.get("represented_year") is None
                else _integer(source, "represented_year")
            ),
            attribution=(
                None
                if source.get("attribution") is None
                else _string(source, "attribution")
            ),
            metadata=tuple(
                _string_pair(item, "metadata") for item in _list(source, "metadata")
            ),
        ),
        association=AssociationStatus(_string(value, "association")),
        semantic_role=_string(value, "semantic_role"),
        component_id=(
            None
            if value.get("component_id") is None
            else _string(value, "component_id")
        ),
        place_name=(
            None if value.get("place_name") is None else _string(value, "place_name")
        ),
        country_code=(
            None
            if value.get("country_code") is None
            else _string(value, "country_code")
        ),
        observed_at=(
            None if observed_at is None else _parse_datetime_value(observed_at)
        ),
        derivation_inputs=tuple(
            _string_value(item, "derivation_inputs")
            for item in _list(value, "derivation_inputs")
        ),
    )


def _temporal_plan_document(plan: TemporalPlan) -> dict[str, Any]:
    onset = plan.onset
    return {
        "reference_time": plan.reference_time.isoformat(),
        "impact_end": None if plan.impact_end is None else plan.impact_end.isoformat(),
        "policy_version": plan.policy_version,
        "recovery_anchor": (
            None if plan.recovery_anchor is None else plan.recovery_anchor.isoformat()
        ),
        "onset": (
            None
            if onset is None
            else {
                "earliest": onset.earliest.isoformat(),
                "latest": onset.latest.isoformat(),
                "source_id": onset.source_id,
                "precision": onset.precision,
            }
        ),
        "windows": [
            {
                "role": item.role.value,
                "sensor": item.sensor.value,
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
                "expanded_start": item.expanded_start.isoformat(),
                "expanded_end": item.expanded_end.isoformat(),
            }
            for item in plan.windows
        ],
    }


def _temporal_plan_from_document(document: Mapping[str, Any]) -> TemporalPlan:
    onset_document = document.get("onset")
    onset = None
    if onset_document is not None:
        onset_value = _mapping_value(onset_document)
        onset = DomainImpactOnset(
            earliest=_datetime(onset_value, "earliest"),
            latest=_datetime(onset_value, "latest"),
            source_id=_string(onset_value, "source_id"),
            precision=cast(OnsetPrecision, _string(onset_value, "precision")),
        )
    return TemporalPlan(
        reference_time=_datetime(document, "reference_time"),
        onset=onset,
        impact_end=(
            None
            if document.get("impact_end") is None
            else _datetime(document, "impact_end")
        ),
        policy_version=_string(document, "policy_version"),
        windows=tuple(
            RoleWindow(
                role=TemporalRole(_string(item, "role")),
                sensor=Sensor(_string(item, "sensor")),
                start=_datetime(item, "start"),
                end=_datetime(item, "end"),
                expanded_start=_datetime(item, "expanded_start"),
                expanded_end=_datetime(item, "expanded_end"),
            )
            for item in _list(document, "windows")
        ),
        recovery_anchor=(
            None
            if document.get("recovery_anchor") is None
            else _datetime(document, "recovery_anchor")
        ),
    )


def _observation_document(observation: Observation) -> dict[str, Any]:
    identity = observation.identity
    quality = observation.quality
    return {
        "observation_id": observation.observation_id,
        "sensor": observation.sensor.value,
        "identity": {
            "product_id": identity.product_id,
            "provider": identity.provider,
            "revision": identity.revision,
            "acquisition_id": identity.acquisition_id,
            "datatake_id": identity.datatake_id,
            "platform": identity.platform,
            "processing_version": identity.processing_version,
            "source_url": identity.source_url,
        },
        "capture": {
            "start": observation.capture.start.isoformat(),
            "end": observation.capture.end.isoformat(),
        },
        "footprint": observation.footprint.as_geojson(),
        "readiness": observation.readiness.value,
        "quality": (
            None
            if quality is None
            else {
                "covered_fraction": quality.covered_fraction,
                "usable_fraction": quality.usable_fraction,
                "obscured_fraction": quality.obscured_fraction,
                "uncertain_fraction": quality.uncertain_fraction,
                "uncovered_fraction": quality.uncovered_fraction,
                "component_usable_fractions": [
                    list(item) for item in quality.component_usable_fractions
                ],
                "quality_state": quality.quality_state.value,
                "mask_definition": quality.mask_definition,
            }
        ),
        "acquisition_group_id": observation.acquisition_group_id,
        "mode": observation.mode,
        "relative_orbit": observation.relative_orbit,
        "orbit_direction": observation.orbit_direction,
        "polarizations": list(observation.polarizations),
        "cloud_cover_fraction": observation.cloud_cover_fraction,
        "recipe_version": observation.recipe_version,
        "provider_published_at": (
            None
            if observation.provider_published_at is None
            else observation.provider_published_at.isoformat()
        ),
        "catalog_updated_at": (
            None
            if observation.catalog_updated_at is None
            else observation.catalog_updated_at.isoformat()
        ),
        "retrieved_at": (
            None
            if observation.retrieved_at is None
            else observation.retrieved_at.isoformat()
        ),
        "assets": [list(item) for item in observation.assets],
    }


def _observation_from_document(document: object) -> Observation:
    value = _mapping_value(document)
    identity = _mapping(value, "identity")
    capture = _mapping(value, "capture")
    quality_document = value.get("quality")
    quality = None
    if quality_document is not None:
        quality_value = _mapping_value(quality_document)
        quality = ObservationQuality(
            covered_fraction=_number(quality_value, "covered_fraction"),
            usable_fraction=_number(quality_value, "usable_fraction"),
            obscured_fraction=_number(quality_value, "obscured_fraction"),
            uncertain_fraction=_number(quality_value, "uncertain_fraction"),
            uncovered_fraction=_number(quality_value, "uncovered_fraction"),
            component_usable_fractions=tuple(
                (
                    _string_first(item, "component_usable_fractions"),
                    _number_item(item),
                )
                for item in _list(quality_value, "component_usable_fractions")
            ),
            quality_state=QualityState(_string(quality_value, "quality_state")),
            mask_definition=_string(quality_value, "mask_definition"),
        )
    return Observation(
        observation_id=_string(value, "observation_id"),
        sensor=Sensor(_string(value, "sensor")),
        identity=AcquisitionIdentity(
            product_id=_string(identity, "product_id"),
            provider=_string(identity, "provider"),
            revision=_optional_string(identity, "revision"),
            acquisition_id=_optional_string(identity, "acquisition_id"),
            datatake_id=_optional_string(identity, "datatake_id"),
            platform=_optional_string(identity, "platform"),
            processing_version=_optional_string(identity, "processing_version"),
            source_url=_optional_string(identity, "source_url"),
        ),
        capture=CaptureInterval(_datetime(capture, "start"), _datetime(capture, "end")),
        footprint=polygon_from_geojson(_mapping(value, "footprint")),
        readiness=ObservationReadiness(_string(value, "readiness")),
        quality=quality,
        acquisition_group_id=_optional_string(value, "acquisition_group_id"),
        mode=_optional_string(value, "mode"),
        relative_orbit=(
            None
            if value.get("relative_orbit") is None
            else _integer(value, "relative_orbit")
        ),
        orbit_direction=_optional_string(value, "orbit_direction"),
        polarizations=tuple(
            _string_value(item, "polarizations")
            for item in _list(value, "polarizations")
        ),
        cloud_cover_fraction=(
            None
            if value.get("cloud_cover_fraction") is None
            else _number(value, "cloud_cover_fraction")
        ),
        recipe_version=_optional_string(value, "recipe_version"),
        provider_published_at=_optional_datetime(value, "provider_published_at"),
        catalog_updated_at=_optional_datetime(value, "catalog_updated_at"),
        retrieved_at=_optional_datetime(value, "retrieved_at"),
        assets=tuple(_string_pair(item, "assets") for item in _list(value, "assets")),
    )


def _selection_document(selection: SelectionResult | None) -> dict[str, Any] | None:
    if selection is None:
        return None
    return {
        "sensors": [
            {
                "sensor": item.sensor.value,
                "selections": [
                    {
                        "role": outcome.role.value,
                        "observation_id": (
                            None
                            if outcome.observation is None
                            else outcome.observation.observation_id
                        ),
                        "reason": outcome.reason.value,
                        "explanation": outcome.explanation,
                        "age_class": (
                            None
                            if outcome.age_class is None
                            else outcome.age_class.value
                        ),
                        "alternative_observation_ids": [
                            item.observation_id for item in outcome.alternatives
                        ],
                    }
                    for outcome in item.selections
                ],
            }
            for item in selection.sensors
        ]
    }


def _selection_from_document(
    document: object,
    plan: TemporalPlan,
    candidates: Mapping[str, Observation],
) -> SelectionResult | None:
    if document is None:
        return None
    value = _mapping_value(document)
    sensors: list[SensorSelection] = []
    for sensor_document in _list(value, "sensors"):
        sensor_value = _mapping_value(sensor_document)
        sensor = Sensor(_string(sensor_value, "sensor"))
        selections: list[GroundImagerySelection] = []
        for outcome_document in _list(sensor_value, "selections"):
            outcome = _mapping_value(outcome_document)
            observation_id = outcome.get("observation_id")
            selected = None
            if observation_id is not None:
                selected = candidates.get(
                    _string_value(observation_id, "observation_id")
                )
                if selected is None:
                    raise ValueError(
                        "A durable imagery selection references no candidate."
                    )
            alternatives = tuple(
                candidates[item]
                for item in _list(outcome, "alternative_observation_ids")
                if _string_value(item, "alternative_observation_ids") in candidates
            )
            selections.append(
                GroundImagerySelection(
                    role=TemporalRole(_string(outcome, "role")),
                    observation=selected,
                    reason=SelectionReason(_string(outcome, "reason")),
                    explanation=_string(outcome, "explanation"),
                    age_class=(
                        None
                        if outcome.get("age_class") is None
                        else _age_class(_string(outcome, "age_class"))
                    ),
                    alternatives=alternatives,
                )
            )
        sensors.append(SensorSelection(sensor=sensor, selections=tuple(selections)))
    return SelectionResult(plan=plan, sensors=tuple(sensors))


def _search_status_from_document(document: object) -> SensorSearchStatus:
    value = _mapping_value(document)
    return SensorSearchStatus(
        sensor=Sensor(_string(value, "sensor")),
        scanned_count=_integer(value, "scanned_count"),
        scan_complete=bool(value.get("scan_complete", False)),
        next_cursor=_optional_string(value, "next_cursor"),
        failure_code=_optional_string(value, "failure_code"),
        failure_detail=_optional_string(value, "failure_detail"),
    )
