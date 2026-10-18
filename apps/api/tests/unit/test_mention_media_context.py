from datetime import UTC, datetime
from typing import cast

from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.discovery_projection import (
    discovery_incident,
)
from disaster_monitor.application.incidents.evidence_context import (
    IncidentEvidenceContextReader,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference


async def test_original_article_url_reaches_media_without_changing_report_identity():
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    source = SourceReference(
        "news",
        "Daily",
        "Regional update",
        "https://reliefweb.int/node/123",
        now,
        None,
        now,
    )
    article = DiscoveryArticle(
        source,
        "Floods hit Riverton. Earthquakes struck Lakeview.",
        original_url="https://www.nbcnews.com/story",
    )
    event = group_reports(
        (assess_article(article, ReportingInterval.at_start(7, now)),)
    )[0]
    incident = discovery_incident(event, now)

    class Incidents:
        async def lookup(self, identifier):
            return incident

    context = await IncidentEvidenceContextReader(
        cast(ActiveIncidentsService, Incidents()), cast(CountryCatalog, object())
    ).read(event.event_id)
    urls = tuple(s.canonical_url for s in context.media.collected_articles)
    assert urls == (source.canonical_url, article.original_url)
    assert context.media.multi_event_article_urls == urls
    assert event.reports[0].article.source.canonical_url == source.canonical_url
    assert not context.media.event_time_known
