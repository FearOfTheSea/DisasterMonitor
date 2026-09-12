from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestState,
    ImageryArtifactReference,
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


def test_request_codec_round_trips_versioned_regions_selections_and_artifacts() -> None:
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

    restored = request_from_document(request_to_document(request))

    assert restored == request
