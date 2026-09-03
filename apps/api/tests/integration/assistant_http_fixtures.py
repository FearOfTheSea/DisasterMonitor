from datetime import UTC, datetime

from disaster_monitor.application.disaster import DisasterQuery, ProviderBatch
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventMeasurement,
    FactStatus,
    MeasurementKind,
    ReportedFact,
    SituationReport,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

CURRENT_PROMPT = (
    "There was a recent earthquake in Japan. Please update me with the latest "
    "information about the damages in Japan."
)
AUGUST_2026_PROMPT = (
    "Please give me the latest information about the earthquake in Japan on "
    "August 5, 2026."
)
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def _required_country(alpha3_code: str) -> Country:
    country = StaticCountryCatalog().get_by_alpha3(alpha3_code)
    if country is None:
        raise RuntimeError(f"HTTP fixture country is missing: {alpha3_code}")
    return country


JAPAN = _required_country("JPN")
VENEZUELA = _required_country("VEN")


def injected_capabilities() -> tuple[ProviderCapabilities, ProviderCapabilities]:
    return (
        ProviderCapabilities(
            frozenset({ProviderRole.EVENT_DISCOVERY}),
            frozenset({Disaster.EARTHQUAKE}),
            None,
        ),
        ProviderCapabilities(
            frozenset({ProviderRole.SITUATION_EVIDENCE}),
            frozenset({Disaster.EARTHQUAKE}),
            None,
        ),
    )


def build_current_service(
    *,
    situation_error: Exception | None = None,
    fact_category: str = "buildings",
    fact_label: str = "Buildings damaged",
    fact_value: str = "4",
    fact_status: FactStatus = FactStatus.CONFIRMED,
) -> CurrentDisasterReportService:
    event_source = SourceReference(
        source_id="fixture-events",
        publisher="Global Catalog",
        title="Fixture earthquake",
        canonical_url="https://example.test/global-catalog-event",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
    )
    selected_event = DisasterEvent(
        event_id="global-catalog:fixture-event",
        disaster=Disaster.EARTHQUAKE,
        location="Ishikawa, Japan",
        country=JAPAN,
        event_time=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
        source=event_source,
        geometry=point_event_geometry(37.0, 137.0, event_source),
        measurements=(
            EventMeasurement(MeasurementKind.MAGNITUDE, 6.1, source=event_source),
            EventMeasurement(
                MeasurementKind.INTENSITY, "Global Catalog 6-", source=event_source
            ),
            EventMeasurement(MeasurementKind.DEPTH, 12, "km", source=event_source),
        ),
    )

    class EventProvider:
        async def find_recent_events(
            self, _query: DisasterQuery, *, now: datetime
        ) -> ProviderBatch[DisasterEvent]:
            return ProviderBatch((selected_event,))

    class SituationProvider:
        async def get_situation_reports(
            self, event: DisasterEvent, _query: DisasterQuery, *, now: datetime
        ) -> ProviderBatch[SituationReport]:
            if situation_error:
                raise situation_error
            situation_source = SourceReference(
                source_id="fixture-situation-reports",
                publisher="Global Reports",
                title="Fixture situation update",
                canonical_url="https://example.test/global-reports-update",
                published_at=NOW,
                updated_at=NOW,
                retrieved_at=NOW,
            )
            return ProviderBatch(
                (
                    SituationReport(
                        source=situation_source,
                        narrative=f"{fact_label}: {fact_value}.",
                        facts=(
                            ReportedFact(
                                category=fact_category,
                                label=fact_label,
                                value=fact_value,
                                status=fact_status,
                                source=situation_source,
                                event_id=event.event_id,
                                claim_id=fact_category,
                            ),
                        ),
                        event_id=event.event_id,
                    ),
                )
            )

    return CurrentDisasterReportService(
        EventProvider(),
        SituationProvider(),
        provider_capabilities=injected_capabilities(),
        clock=lambda: NOW,
    )
