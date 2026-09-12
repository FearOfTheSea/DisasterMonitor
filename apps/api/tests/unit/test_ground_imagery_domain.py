from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    Coordinate,
    RegionEvidence,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)


def _source() -> RegionSource:
    return RegionSource(
        source_id="cems:emsr720",
        source_kind=RegionSourceKind.MAPPED_IMPACT,
        publisher="Copernicus EMS",
        reference="https://example.test/emsr720",
        captured_at=datetime(2024, 5, 20, tzinfo=UTC),
        attribution="Copernicus EMS",
    )


def test_geojson_parser_preserves_multipolygon_holes_and_axis_order() -> None:
    geometry = polygon_from_geojson(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [[10, 1], [12, 1], [12, 3], [10, 3], [10, 1]],
                    [[10.5, 1.5], [11, 1.5], [11, 2], [10.5, 2], [10.5, 1.5]],
                ],
                [[[20, 1], [21, 1], [21, 2], [20, 2], [20, 1]]],
            ],
        }
    )

    assert len(geometry.polygons) == 2
    assert len(geometry.polygons[0].holes) == 1
    assert geometry.polygons[0].exterior.coordinates[0] == Coordinate(1, 10)
    assert geometry.as_geojson()["coordinates"][1][0][0] == [20, 1]
    assert geometry.positions == 15


def test_region_evidence_normalizes_country_and_retains_source_semantics() -> None:
    evidence = RegionEvidence(
        evidence_id="flood-component:west",
        geometry=polygon_from_geojson(
            {
                "type": "Polygon",
                "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
            }
        ),
        source=_source(),
        association=AssociationStatus.POSSIBLE,
        semantic_role="observed_flood_component",
        country_code="bra",
        component_id="west",
    )

    assert evidence.country_code == "BRA"
    assert evidence.source.source_kind is RegionSourceKind.MAPPED_IMPACT
    assert evidence.association is AssociationStatus.POSSIBLE


@pytest.mark.parametrize(
    "geometry",
    (
        {"type": "Point", "coordinates": [10, 1]},
        {
            "type": "Polygon",
            "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2]]],
        },
        {
            "type": "Polygon",
            "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1, 4]]],
        },
    ),
)
def test_invalid_or_non_area_geojson_is_rejected(geometry: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        polygon_from_geojson(geometry)
