from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import DisasterQuery, ProviderBatch
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    Country,
    CycloneMapCoordinate,
    CycloneMapGeometryKind,
    CycloneMapLayer,
    CycloneMapSemanticRole,
    Disaster,
    DisasterEvent,
    EventGeometry,
    GeographicArea,
    SituationReport,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)

NOW = datetime(2026, 8, 31, 3, tzinfo=UTC)


def _source() -> SourceReference:
    return SourceReference(
        source_id="official-cyclone-forecast",
        publisher="Official forecast centre",
        title="Forecast product",
        canonical_url="https://forecast.example/product.kmz",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW + timedelta(minutes=2),
        authority=SourceAuthority.NATIONAL_AUTHORITY,
    )


COUNTRY = Country("TST", "Testland", (), GeographicArea(-90, 90, -180, 180), "UTC")


def _coordinate(
    latitude: float = 17.0,
    longitude: float = -124.0,
    *,
    valid_at: datetime | None = NOW + timedelta(hours=12),
) -> CycloneMapCoordinate:
    return CycloneMapCoordinate(latitude, longitude, valid_at)


def test_forecast_track_is_separate_from_event_geometry_and_preserves_times() -> None:
    layer = CycloneMapLayer(
        layer_id="forecast:track:1",
        semantic_role=CycloneMapSemanticRole.FORECAST_TRACK,
        geometry_kind=CycloneMapGeometryKind.TRACK,
        coordinates=(
            _coordinate(),
            _coordinate(18.0, -126.0, valid_at=NOW + timedelta(hours=24)),
        ),
        source=_source(),
        issued_at=NOW,
        valid_from=NOW + timedelta(hours=12),
        valid_to=NOW + timedelta(hours=24),
        storm_id="EP112026",
        provisional=False,
        limitation="Official forecast points; not an observed storm footprint.",
        reconciliation="Unique authoritative storm identifier match.",
    )

    assert not isinstance(layer, EventGeometry)
    assert layer.semantic_role is CycloneMapSemanticRole.FORECAST_TRACK
    assert layer.coordinates[1].valid_at == NOW + timedelta(hours=24)
    assert layer.issued_at.tzinfo is UTC


def test_semantic_roles_enforce_geometry_and_provisional_distinctions() -> None:
    with pytest.raises(ValueError, match="Provisional track"):
        CycloneMapLayer(
            "bad-provisional",
            CycloneMapSemanticRole.PROVISIONAL_TRACK,
            CycloneMapGeometryKind.TRACK,
            (_coordinate(), _coordinate(18, -126)),
            _source(),
            NOW,
            NOW,
            NOW + timedelta(hours=12),
            "storm",
            False,
            "limitation",
            "reconciliation",
        )
    with pytest.raises(ValueError, match="Forecast track"):
        CycloneMapLayer(
            "bad-forecast",
            CycloneMapSemanticRole.FORECAST_TRACK,
            CycloneMapGeometryKind.AREA,
            (_coordinate(), _coordinate(18, -126), _coordinate(19, -125)),
            _source(),
            NOW,
            NOW,
            NOW + timedelta(hours=12),
            "storm",
            False,
            "limitation",
            "reconciliation",
        )
    with pytest.raises(ValueError, match="Uncertainty"):
        CycloneMapLayer(
            "bad-cone",
            CycloneMapSemanticRole.UNCERTAINTY_AREA,
            CycloneMapGeometryKind.TRACK,
            (_coordinate(), _coordinate(18, -126)),
            _source(),
            NOW,
            NOW,
            NOW + timedelta(hours=12),
            "storm",
            False,
            "limitation",
            "reconciliation",
        )


def test_coordinates_and_all_product_times_are_validated() -> None:
    with pytest.raises(ValueError, match="WGS84"):
        _coordinate(latitude=91)
    with pytest.raises(ValueError, match="timezone-aware"):
        _coordinate(valid_at=datetime(2026, 8, 31, 3))
    with pytest.raises(ValueError, match="timezone-aware"):
        CycloneMapLayer(
            "bad-time",
            CycloneMapSemanticRole.FORECAST_TRACK,
            CycloneMapGeometryKind.TRACK,
            (_coordinate(), _coordinate(18, -126)),
            _source(),
            datetime(2026, 8, 31, 3),
            NOW,
            NOW + timedelta(hours=12),
            "storm",
            False,
            "limitation",
            "reconciliation",
        )


def test_missing_provenance_and_wind_threshold_metadata_are_rejected() -> None:
    with pytest.raises(TypeError, match="source provenance"):
        CycloneMapLayer(
            "missing-source",
            CycloneMapSemanticRole.FORECAST_TRACK,
            CycloneMapGeometryKind.TRACK,
            (_coordinate(), _coordinate(18, -126)),
            None,  # type: ignore[arg-type]
            NOW,
            NOW,
            NOW + timedelta(hours=12),
            "storm",
            False,
            "limitation",
            "reconciliation",
        )
    with pytest.raises(ValueError, match="Wind-radii"):
        CycloneMapLayer(
            "wind",
            CycloneMapSemanticRole.WIND_RADII,
            CycloneMapGeometryKind.AREA,
            (_coordinate(), _coordinate(18, -126), _coordinate(19, -125)),
            _source(),
            NOW,
            NOW,
            NOW + timedelta(hours=12),
            "storm",
            False,
            "limitation",
            "reconciliation",
        )


@pytest.mark.asyncio
async def test_selected_event_flow_retains_supplemental_geometry_separately() -> None:
    event_source = SourceReference(
        source_id="gdacs-tropical-cyclones",
        publisher="GDACS",
        title="Tropical Cyclone FIXTURE-26",
        canonical_url="https://www.gdacs.org/report.aspx?eventid=1",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
        authority=SourceAuthority.SECONDARY,
    )
    event_geometry = point_event_geometry(17.0, -123.0, event_source)
    event = DisasterEvent(
        event_id="gdacs:tc:1",
        disaster=Disaster.TROPICAL_CYCLONE,
        location="Testland coast",
        country=COUNTRY,
        event_time=NOW,
        source=event_source,
        geometry=event_geometry,
    )
    layer = CycloneMapLayer(
        layer_id="forecast:track:fixture",
        semantic_role=CycloneMapSemanticRole.FORECAST_TRACK,
        geometry_kind=CycloneMapGeometryKind.TRACK,
        coordinates=(
            _coordinate(valid_at=NOW + timedelta(hours=12)),
            _coordinate(18, -126, valid_at=NOW + timedelta(hours=24)),
        ),
        source=_source(),
        issued_at=NOW,
        valid_from=NOW + timedelta(hours=12),
        valid_to=NOW + timedelta(hours=24),
        storm_id="EP112026",
        provisional=False,
        limitation="Official forecast points; not an observed storm footprint.",
        reconciliation="Unique name and point match.",
    )

    class EventProvider:
        async def find_recent_events(self, query, *, now):
            return ProviderBatch((event,))

    class SituationProvider:
        async def get_situation_reports(self, selected, query, *, now):
            return ProviderBatch(
                (
                    SituationReport(
                        source=layer.source,
                        narrative="Official forecast geometry matched uniquely.",
                        event_id=selected.event_id,
                        correlation=CorrelationStatus.MATCHED,
                        reported_event_time=selected.event_time,
                        countries=(COUNTRY.canonical_name,),
                        country_codes=(COUNTRY.alpha3_code,),
                        disaster=Disaster.TROPICAL_CYCLONE,
                        supplemental_geometry=(layer,),
                    ),
                )
            )

    service = CurrentDisasterReportService(
        EventProvider(),
        SituationProvider(),
        provider_capabilities=(
            ProviderCapabilities(
                frozenset({ProviderRole.EVENT_DISCOVERY}),
                frozenset({Disaster.TROPICAL_CYCLONE}),
                None,
            ),
            ProviderCapabilities(
                frozenset({ProviderRole.SITUATION_EVIDENCE}),
                frozenset({Disaster.TROPICAL_CYCLONE}),
                None,
            ),
        ),
        clock=lambda: NOW,
    )

    report = await service.execute(
        DisasterQuery(
            Disaster.TROPICAL_CYCLONE,
            COUNTRY,
            "recent",
            ("latest",),
        )
    )

    assert report.selected_event is not None
    assert report.selected_event.geometry is event_geometry
    assert report.selected_event.supplemental_geometry == (layer,)
