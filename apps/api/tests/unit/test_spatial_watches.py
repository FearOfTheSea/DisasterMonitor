from datetime import UTC, datetime

from disaster_monitor.application.watches.evaluate_asset_exposure import (
    AssetExposureWatchEvaluator,
)
from disaster_monitor.domain.imagery.regions import Coordinate, polygon_from_geojson
from disaster_monitor.domain.spatial_watches import (
    AreaOfInterestScope,
    LocalAsset,
    LocalAssetKind,
    SpatialInputKind,
    WatchGeometryEvidence,
    WatchGeometryRole,
    WatchTriggerPolicy,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def test_aoi_factories_preserve_shape_kind_and_geometry_version() -> None:
    box = AreaOfInterestScope.bounding_box(
        scope_id="aoi:warehouse",
        name="Warehouse district",
        min_latitude=10,
        min_longitude=106,
        max_latitude=11,
        max_longitude=107,
        version="operator-edit:3",
        updated_at=NOW,
    )
    circle = AreaOfInterestScope.circle(
        scope_id="aoi:port",
        name="Port radius",
        center=Coordinate(10.5, 106.5),
        radius_km=10,
        version="operator-edit:1",
        updated_at=NOW,
    )

    assert box.input_kind is SpatialInputKind.BOUNDING_BOX
    assert circle.input_kind is SpatialInputKind.CIRCLE
    assert box.geometry.sha256() != circle.geometry.sha256()
    assert box.version == "operator-edit:3"


def test_asset_trigger_is_deterministic_and_retains_causing_geometry() -> None:
    source_geometry = polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [[[106, 10], [107, 10], [107, 11], [106, 11], [106, 10]]],
        }
    )
    evidence = WatchGeometryEvidence(
        evidence_id="cap:warning-7",
        geometry=source_geometry,
        geometry_version="cap-sent:2026-09-14T00:00:00Z",
        role=WatchGeometryRole.OFFICIAL_WARNING,
        source_id="meteoalarm-at",
        observed_at=NOW,
    )
    asset = LocalAsset(
        asset_id="asset:warehouse",
        name="Warehouse",
        kind=LocalAssetKind.WAREHOUSE,
        version="operator-edit:2",
        coordinate=Coordinate(10.5, 106.5),
        updated_at=NOW,
    )

    finding = AssetExposureWatchEvaluator().evaluate(
        watch_id="watch:assets",
        evidence=evidence,
        assets=(asset,),
        policy=WatchTriggerPolicy(max_distance_km=0),
        evaluated_at=NOW,
    )[0]

    assert finding.geometry_hash == source_geometry.sha256()
    assert finding.geometry_version == "cap-sent:2026-09-14T00:00:00Z"
    assert finding.asset_version == "operator-edit:2"
    assert finding.summary == "Warehouse intersects an official warning area"
    assert "affected" not in finding.summary.casefold()
