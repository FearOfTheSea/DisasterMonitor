"""Only the selected dated occurrence gets bounded optional geography lookup."""

from datetime import UTC, datetime

from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.ports.mention_geography import PlaceResolution
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.events import (
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)


async def test_selected_place_resolution_keeps_original_scan_and_event_evidence(
    tmp_path,
):
    now = datetime(2026, 10, 19, tzinfo=UTC)
    source = SourceReference(
        "news", "Daily", "Flood update", "https://news.example/report", now, None, now
    )
    article = DiscoveryArticle(
        source, "Floods hit Riverton on 26 August.", location="Exampleland"
    )
    interval = ReportingInterval.at_start(30, now)
    reports = (assess_article(article, interval),)
    events = group_reports(reports)
    original = DiscoveryRun(
        "11111111-1111-4111-8111-111111111111",
        interval,
        status="completed",
        reports=reports,
        events=events,
        finished_at=now,
    )
    store = FileDiscoveryStore(tmp_path)
    await store.save(original)
    geometry = EventGeometry(
        kind=EventGeometryKind.AREA,
        coordinates=(
            EventCoordinate(1, 1),
            EventCoordinate(1, 2),
            EventCoordinate(2, 2),
            EventCoordinate(1, 1),
        ),
        source=source,
        estimated=True,
        description="Administrative context, not a damage footprint.",
    )

    class Resolver:
        calls = []

        async def resolve(self, place, country_context):
            self.calls.append((place, country_context))
            return PlaceResolution(
                "resolved", geometry, "Attributed geographic context"
            )

    resolver = Resolver()
    service = ActiveIncidentsService(
        ProviderRegistry(()),
        country_catalog=StaticCountryCatalog(),
        discovery_store=store,
        discovery_place_resolver=resolver,
    )
    result = await service.lookup(events[0].event_id)
    assert result.geometry == geometry
    assert result.discovery_event.reports[0].article == article
    assert resolver.calls == [("Riverton", "Exampleland")]
    assert await store.read(original.scan_id) == original
