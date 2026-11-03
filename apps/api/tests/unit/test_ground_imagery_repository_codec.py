from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestState,
    ImageryArtifactReference,
    ImageryPreparationFailure,
)
from disaster_monitor.application.ground_imagery.resolve_region import (
    RegionResolution,
    RegionResolutionState,
)
from disaster_monitor.application.ground_imagery.select_observations import (
    select_observations,
)
from disaster_monitor.application.ground_imagery.temporal_policy import (
    ImpactOnset,
    build_temporal_plan,
)
from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid
from disaster_monitor.application.ports.ground_imagery.repository_codec import (
    request_from_document,
    request_to_document,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationQuality,
    ObservationReadiness,
    QualityState,
    Sensor,
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


def _request_fixture() -> GroundImageryRequest:
    timestamp = datetime(2024, 5, 1, tzinfo=UTC)
    geometry = polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
        }
    )
    source = RegionSource(
        source_id="fixture:impact",
        source_kind=RegionSourceKind.MAPPED_IMPACT,
        publisher="Fixture",
        reference="https://example.test/impact",
    )
    evidence = RegionEvidence(
        evidence_id="impact",
        geometry=geometry,
        source=source,
        association=AssociationStatus.CONFIRMED,
        semantic_role="mapped impact",
    )
    region = ImageryRegionVersion(
        region_id="region:1",
        version=1,
        core=geometry,
        inspection=geometry,
        source_footprints=(evidence,),
        core_role=RegionRole.CORE,
    )
    onset = ImpactOnset.exact(timestamp, source_id="fixture:event")
    plan = build_temporal_plan(
        onset=onset,
        reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        disaster=Disaster.FLOOD,
    )
    observation = Observation(
        observation_id="s1-1",
        sensor=Sensor.SENTINEL_1,
        identity=AcquisitionIdentity(
            product_id="product-1",
            provider="fixture",
            acquisition_id="acquisition-1",
            revision="r1",
        ),
        capture=CaptureInterval(timestamp, timestamp + timedelta(minutes=5)),
        footprint=geometry,
        readiness=ObservationReadiness.RENDERABLE,
        quality=ObservationQuality(
            covered_fraction=1,
            usable_fraction=0.9,
            obscured_fraction=0.1,
            uncertain_fraction=0,
            uncovered_fraction=0,
            component_usable_fractions=(("core", 0.9),),
            quality_state=QualityState.USEFUL,
            mask_definition="fixture-v1",
        ),
        mode="IW",
        relative_orbit=24,
        orbit_direction="descending",
        polarizations=("VV", "VH"),
    )
    selection = select_observations(
        plan,
        {Sensor.SENTINEL_1: (observation,), Sensor.SENTINEL_2: ()},
        disaster=Disaster.FLOOD,
    )
    artifact = ImageryArtifactReference(
        artifact_id="artifact:1",
        selection_id="selection:1",
        sensor=Sensor.SENTINEL_1,
        role=selection.for_sensor(Sensor.SENTINEL_1).selections[0].role,
        output_kind="s1-backscatter-display",
        content_type="image/tiff",
        storage_key="artifact:1.bin",
        byte_count=10,
        sha256="a" * 64,
        source_product_ids=("product-1",),
        grid=ImageryGrid("EPSG:32632", 0, 0, 100, 100, 10, 10, 10, "native-10m"),
        created_at=datetime(2024, 5, 20, tzinfo=UTC),
        observation=observation,
    )
    request = GroundImageryRequest(
        request_id="ground-imagery:1",
        request_version=2,
        incident_id="incident-1",
        disaster=Disaster.FLOOD,
        reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        requested_sensors=(Sensor.SENTINEL_1, Sensor.SENTINEL_2),
        region_resolution=RegionResolution(RegionResolutionState.RESOLVED, region),
        temporal_plan=plan,
        candidates=(observation,),
        search_status=(),
        selection=selection,
        state=GroundImageryRequestState.PARTIAL,
        reason_codes=("partial_coverage",),
        created_at=datetime(2024, 5, 20, tzinfo=UTC),
        updated_at=datetime(2024, 5, 20, tzinfo=UTC),
        artifacts=(artifact,),
    )

    return request


def test_request_codec_round_trips_versioned_regions_selections_and_artifacts() -> None:
    request = _request_fixture()
    restored = request_from_document(request_to_document(request))

    assert restored == request


@pytest.mark.parametrize(
    "field", ["watch_enabled", "scan_complete", "preparation_failure_scope_unknown"]
)
@pytest.mark.parametrize("invalid", ["false", 1, None])
def test_request_codec_rejects_nonboolean_fields(field: str, invalid: object) -> None:
    document = request_to_document(_request_fixture())
    if field == "scan_complete":
        document["search_status"] = [
            {"sensor": "sentinel-1", "scanned_count": 0, "scan_complete": invalid}
        ]
    else:
        document[field] = invalid

    with pytest.raises(ValueError, match=field):
        request_from_document(document)


@pytest.mark.asyncio
async def test_preparation_failure_and_recovery_survive_file_store_reopen(tmp_path):
    from disaster_monitor.infrastructure.ground_imagery.file_repository import (
        FileGroundImageryRequestStore,
    )

    request = _request_fixture()
    failure = ImageryPreparationFailure(
        request_version=request.request_version,
        selection_id="selection:failed",
        artifact_id="artifact:failed",
        failed_at=request.created_at,
        recovered_at=request.created_at + timedelta(minutes=1),
        failure_count=2,
    )
    unresolved = replace(failure, artifact_id="artifact:other-grid", recovered_at=None)
    request = replace(
        request,
        preparation_failures=(failure, unresolved),
        reason_codes=("artifact_preparation_failed",),
    )
    path = tmp_path / "requests.json"
    await FileGroundImageryRequestStore(path).save_request(request)
    restored = await FileGroundImageryRequestStore(path).get_request(request.request_id)
    assert restored == request
    assert restored.preparation_failures[0].recovered_at == failure.recovered_at
    assert restored.preparation_failures[1].recovered_at is None


def test_legacy_failure_without_a_target_is_not_assumed_recovered():
    document = request_to_document(_request_fixture())
    document["reason_codes"] = ["artifact_preparation_failed"]
    del document["preparation_failures"]
    del document["preparation_failure_scope_unknown"]
    restored = request_from_document(document)
    assert restored.preparation_failure_scope_unknown is True
    assert restored.reason_codes == ("artifact_preparation_failed",)
    assert request_from_document(request_to_document(restored)) == restored


def test_request_codec_preserves_absent_legacy_boolean_defaults() -> None:
    document = request_to_document(_request_fixture())
    del document["watch_enabled"]
    document["search_status"] = [{"sensor": "sentinel-1", "scanned_count": 0}]

    restored = request_from_document(document)

    assert restored.watch_enabled is False
    assert restored.search_status[0].scan_complete is False


def test_request_codec_rejects_missing_selection_alternative() -> None:
    document = request_to_document(_request_fixture())
    document["selection"]["sensors"][0]["selections"][0][
        "alternative_observation_ids"
    ] = ["missing-observation"]

    with pytest.raises(ValueError, match="alternative"):
        request_from_document(document)


@pytest.mark.asyncio
async def test_file_repository_recovers_request_and_artifact_metadata(tmp_path):
    from importlib import import_module

    module = import_module(
        "disaster_monitor.infrastructure.ground_imagery.file_repository"
    )
    request = _request_fixture()
    repository = module.FileGroundImageryRequestStore(tmp_path / "requests.json")
    await repository.save_request(request)
    restored = module.FileGroundImageryRequestStore(tmp_path / "requests.json")
    assert await restored.get_request(request.request_id) == request
    assert (
        await restored.get_request_for_selection(request.artifacts[0].selection_id)
        == request
    )


async def test_restart_retains_artifacts_and_marks_preparation_interrupted(
    tmp_path,
):
    from dataclasses import replace

    from disaster_monitor.infrastructure.ground_imagery.file_repository import (
        FileGroundImageryRequestStore,
    )

    request = replace(_request_fixture(), state=GroundImageryRequestState.QUEUED)
    path = tmp_path / "requests.json"
    store = FileGroundImageryRequestStore(path)
    await store.save_request(request)
    restored = await FileGroundImageryRequestStore(path).get_request(request.request_id)
    assert restored.state is GroundImageryRequestState.FAILED
    assert "interrupted_restart" in restored.reason_codes
    assert restored.artifacts == request.artifacts
    assert restored.request_version == request.request_version + 1
