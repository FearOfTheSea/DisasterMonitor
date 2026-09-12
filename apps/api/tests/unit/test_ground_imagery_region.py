from datetime import UTC, datetime

from disaster_monitor.application.ground_imagery.resolve_region import (
    IncidentImageryContext,
    RegionResolutionState,
    RegionResolver,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    Coordinate,
    MultiPolygon,
    RegionEvidence,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)
from disaster_monitor.infrastructure.ground_imagery.geometry import (
    GeodesicGeometryEngine,
)


def _source(kind: RegionSourceKind, source_id: str) -> RegionSource:
    return RegionSource(
        source_id=source_id,
        source_kind=kind,
        publisher="Test source",
        reference=f"https://example.test/{source_id}",
    )


def _polygon(minimum: float = 10) -> MultiPolygon:
    return polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [minimum, 1],
                    [minimum + 1, 1],
                    [minimum + 1, 2],
                    [minimum, 2],
                    [minimum, 1],
                ]
            ],
        }
    )


def _context(
    *evidence: RegionEvidence, point: Coordinate | None = None
) -> IncidentImageryContext:
    return IncidentImageryContext(
        incident_id="incident-1",
        disaster=Disaster.FLOOD,
        country_code="BRA",
        event_time=datetime(2024, 5, 5, tzinfo=UTC),
        evidence=evidence,
        verified_point=point,
    )


def test_region_resolver_prefers_associated_impact_over_modeled_or_point() -> None:
    mapped = RegionEvidence(
        evidence_id="mapped",
        geometry=_polygon(),
        source=_source(RegionSourceKind.MAPPED_IMPACT, "mapped"),
        association=AssociationStatus.CONFIRMED,
        semantic_role="mapped impact",
    )
    modeled = RegionEvidence(
        evidence_id="modeled",
        geometry=_polygon(20),
        source=_source(RegionSourceKind.MODELED_HAZARD, "modeled"),
        association=AssociationStatus.CONFIRMED,
        semantic_role="modeled hazard",
    )

    result = RegionResolver(GeodesicGeometryEngine()).resolve(
        _context(mapped, modeled, point=Coordinate(1.5, 10.5))
    )

    assert result.state is RegionResolutionState.RESOLVED
    assert result.region is not None
    assert result.region.core == mapped.geometry
    assert result.region.source_footprints[0].evidence_id == "mapped"
    assert result.region.inspection != result.region.core


def test_acquisition_footprint_cannot_become_an_impact_region() -> None:
    acquisition = RegionEvidence(
        evidence_id="tile-center",
        geometry=_polygon(),
        source=_source(RegionSourceKind.ACQUISITION_FOOTPRINT, "tile"),
        association=AssociationStatus.UNKNOWN,
        semantic_role="satellite acquisition footprint",
    )

    result = RegionResolver(GeodesicGeometryEngine()).resolve(
        _context(acquisition, point=Coordinate(1.5, 10.5))
    )

    assert result.state is RegionResolutionState.RESOLVED
    assert result.region is not None
    assert result.region.core_role.value == "core"
    assert (
        result.region.source_footprints[0].source.source_kind
        is RegionSourceKind.VERIFIED_EVENT_POINT
    )
    assert any("acquisition" in warning.lower() for warning in result.warnings)


def test_competing_same_priority_regions_are_selectable_not_unioned() -> None:
    first = RegionEvidence(
        evidence_id="west",
        geometry=_polygon(),
        source=_source(RegionSourceKind.OBSERVATION_MASK, "west"),
        association=AssociationStatus.POSSIBLE,
        semantic_role="flood component",
    )
    second = RegionEvidence(
        evidence_id="east",
        geometry=_polygon(20),
        source=_source(RegionSourceKind.OBSERVATION_MASK, "east"),
        association=AssociationStatus.POSSIBLE,
        semantic_role="flood component",
    )

    result = RegionResolver(GeodesicGeometryEngine()).resolve(_context(first, second))

    assert result.state is RegionResolutionState.AMBIGUOUS
    assert result.region is None
    assert [item.evidence_id for item in result.alternatives] == ["west", "east"]
