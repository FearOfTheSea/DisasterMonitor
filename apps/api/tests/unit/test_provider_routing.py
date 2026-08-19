from datetime import UTC, datetime

import pytest

from disaster_monitor.application.disaster import DisasterQuery, ProviderBatch
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    SituationReport,
    SourceReference,
)
from disaster_monitor.infrastructure.composition import build_current_disaster_report
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
    CompositeSituationReportProvider,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
VENEZUELA = CATALOG.get_by_alpha3("VEN")
assert JAPAN is not None and VENEZUELA is not None


def _query(disaster: Disaster, country=JAPAN) -> DisasterQuery:
    return DisasterQuery(disaster, country, "recent", ("latest developments",))


class RecordingEventProvider:
    def __init__(self, name: str, source_id: str) -> None:
        self.provider_name = name
        self.source_id = source_id
        self.queries: list[DisasterQuery] = []

    async def find_recent_events(self, query: DisasterQuery, *, now: datetime):
        self.queries.append(query)
        source = SourceReference(
            self.source_id,
            self.provider_name,
            f"{self.provider_name} event",
            f"https://example.test/{self.provider_name}",
            now,
            now,
            now,
        )
        return ProviderBatch(
            (
                DisasterEvent(
                    f"{self.provider_name}:event",
                    query.disaster,
                    query.country.canonical_name,
                    query.country,
                    now,
                    source,
                ),
            )
        )


class RecordingSituationProvider:
    provider_name = "Global Situation"

    def __init__(self) -> None:
        self.queries: list[DisasterQuery] = []

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ):
        self.queries.append(query)
        return ProviderBatch[SituationReport]()


def _registry():
    global_catalog = RecordingEventProvider("Global Catalog", "global-catalog-events")
    usgs = RecordingEventProvider("USGS", "usgs-events")
    global_situation = RecordingSituationProvider()
    event_japan = ProviderCapabilities(
        frozenset({ProviderRole.EVENT_DISCOVERY}),
        frozenset({Disaster.EARTHQUAKE}),
        frozenset({"JPN"}),
    )
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "Global Catalog",
                global_catalog,
                event_japan,
                source_id="global-catalog-events",
                allowed_hosts=frozenset({"example.test"}),
                event_provider=global_catalog,
            ),
            ProviderRegistration(
                "USGS",
                usgs,
                ProviderCapabilities(
                    frozenset({ProviderRole.EVENT_DISCOVERY}),
                    frozenset({Disaster.EARTHQUAKE}),
                    None,
                ),
                source_id="usgs-events",
                allowed_hosts=frozenset({"example.test"}),
                event_provider=usgs,
            ),
            ProviderRegistration(
                "Global Situation",
                global_situation,
                ProviderCapabilities(
                    frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    frozenset({Disaster.EARTHQUAKE}),
                    frozenset({"JPN"}),
                ),
                source_id="global-situation-reports",
                allowed_hosts=frozenset({"example.test"}),
                situation_provider=global_situation,
            ),
            ProviderRegistration(
                "Global Reports",
                object(),
                ProviderCapabilities(
                    frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    frozenset(Disaster),
                    None,
                    requires_configuration=True,
                ),
                source_id="global-reports-reports",
                configured=False,
                allowed_hosts=frozenset({"example.test"}),
                situation_provider=global_situation,
            ),
        )
    )
    return registry, global_catalog, usgs, global_situation


@pytest.mark.asyncio
async def test_capabilities_include_japan_providers_and_exclude_them_abroad() -> None:
    registry, global_catalog, usgs, global_situation = _registry()
    events = CompositeDisasterEventProvider(registry)
    situations = CompositeSituationReportProvider(registry)

    japan_query = _query(Disaster.EARTHQUAKE)
    japan_batch = await events.find_recent_events(japan_query, now=NOW)
    await situations.get_situation_reports(japan_batch.records[0], japan_query, now=NOW)
    assert global_catalog.queries == [japan_query]
    assert usgs.queries == [japan_query]
    assert global_situation.queries == [japan_query]

    venezuela_query = _query(Disaster.EARTHQUAKE, VENEZUELA)
    foreign_batch = await events.find_recent_events(venezuela_query, now=NOW)
    await situations.get_situation_reports(
        foreign_batch.records[0], venezuela_query, now=NOW
    )
    assert global_catalog.queries == [japan_query]
    assert usgs.queries == [japan_query, venezuela_query]
    assert global_situation.queries == [japan_query]


@pytest.mark.asyncio
async def test_unsupported_disaster_invokes_no_earthquake_event_provider() -> None:
    registry, global_catalog, usgs, _global_situation = _registry()
    result = await CompositeDisasterEventProvider(registry).find_recent_events(
        _query(Disaster.WILDFIRE), now=NOW
    )

    assert result.records == ()
    assert global_catalog.queries == []
    assert usgs.queries == []


def test_disabled_global_reports_is_a_configuration_limitation() -> None:
    registry, _global_catalog, _usgs, _global_situation = _registry()
    selection = registry.select(
        _query(Disaster.EARTHQUAKE), ProviderRole.SITUATION_EVIDENCE
    )

    assert [item.name for item in selection.registrations] == ["Global Situation"]
    assert selection.unavailable_configuration == ("Global Reports",)


@pytest.mark.asyncio
async def test_gfm_is_routable_for_every_catalog_country() -> None:
    service = build_current_disaster_report(Settings(), country_catalog=CATALOG)
    try:
        registry = service._provider_registry  # noqa: SLF001
        for country in CATALOG.countries():
            selection = registry.select(
                _query(Disaster.FLOOD, country), ProviderRole.EVENT_DISCOVERY
            )
            assert [item.name for item in selection.registrations] == [
                "CEMS Global Flood Monitoring (GFM)"
            ]
    finally:
        await service.aclose()
