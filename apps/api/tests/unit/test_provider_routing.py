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
    DisasterEvent,
    Hazard,
    SituationReport,
    SourceReference,
)
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


def _query(hazard: Hazard, country=JAPAN) -> DisasterQuery:
    return DisasterQuery(hazard, country, "recent", ("latest developments",))


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
                    query.hazard,
                    query.country.canonical_name,
                    query.country,
                    now,
                    source,
                ),
            )
        )


class RecordingSituationProvider:
    provider_name = "FDMA"

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
    jma = RecordingEventProvider("JMA", "jma-events")
    usgs = RecordingEventProvider("USGS", "usgs-events")
    fdma = RecordingSituationProvider()
    event_japan = ProviderCapabilities(
        frozenset({ProviderRole.EVENT_DISCOVERY}),
        frozenset({Hazard.EARTHQUAKE}),
        frozenset({"JPN"}),
    )
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "JMA",
                jma,
                event_japan,
                source_id="jma-events",
                allowed_hosts=frozenset({"example.test"}),
            ),
            ProviderRegistration(
                "USGS",
                usgs,
                ProviderCapabilities(
                    frozenset({ProviderRole.EVENT_DISCOVERY}),
                    frozenset({Hazard.EARTHQUAKE}),
                    None,
                ),
                source_id="usgs-events",
                allowed_hosts=frozenset({"example.test"}),
            ),
            ProviderRegistration(
                "FDMA",
                fdma,
                ProviderCapabilities(
                    frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    frozenset({Hazard.EARTHQUAKE}),
                    frozenset({"JPN"}),
                ),
                source_id="fdma-reports",
                allowed_hosts=frozenset({"example.test"}),
            ),
            ProviderRegistration(
                "ReliefWeb",
                object(),
                ProviderCapabilities(
                    frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    frozenset(Hazard),
                    None,
                    requires_configuration=True,
                ),
                source_id="reliefweb-reports",
                configured=False,
                allowed_hosts=frozenset({"example.test"}),
            ),
        )
    )
    return registry, jma, usgs, fdma


@pytest.mark.asyncio
async def test_capabilities_include_japan_providers_and_exclude_them_abroad() -> None:
    registry, jma, usgs, fdma = _registry()
    events = CompositeDisasterEventProvider(registry)
    situations = CompositeSituationReportProvider(registry)

    japan_query = _query(Hazard.EARTHQUAKE)
    japan_batch = await events.find_recent_events(japan_query, now=NOW)
    await situations.get_situation_reports(japan_batch.records[0], japan_query, now=NOW)
    assert jma.queries == [japan_query]
    assert usgs.queries == [japan_query]
    assert fdma.queries == [japan_query]

    venezuela_query = _query(Hazard.EARTHQUAKE, VENEZUELA)
    foreign_batch = await events.find_recent_events(venezuela_query, now=NOW)
    await situations.get_situation_reports(
        foreign_batch.records[0], venezuela_query, now=NOW
    )
    assert jma.queries == [japan_query]
    assert usgs.queries == [japan_query, venezuela_query]
    assert fdma.queries == [japan_query]


@pytest.mark.asyncio
async def test_unsupported_hazard_invokes_no_earthquake_event_provider() -> None:
    registry, jma, usgs, _fdma = _registry()
    result = await CompositeDisasterEventProvider(registry).find_recent_events(
        _query(Hazard.WILDFIRE), now=NOW
    )

    assert result.records == ()
    assert jma.queries == []
    assert usgs.queries == []


def test_disabled_reliefweb_is_a_configuration_limitation() -> None:
    registry, _jma, _usgs, _fdma = _registry()
    selection = registry.select(
        _query(Hazard.EARTHQUAKE), ProviderRole.SITUATION_EVIDENCE
    )

    assert [item.name for item in selection.registrations] == ["FDMA"]
    assert selection.unavailable_configuration == ("ReliefWeb",)
