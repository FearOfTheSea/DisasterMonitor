"""Public date-index citations are hints, never publisher facts or publication dates."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.domain.collection import (
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.infrastructure.news.wikipedia_collection import (
    WikipediaCitationCollectionProvider,
)

NOW = datetime(2026, 10, 20, 4, tzinfo=UTC)
HTML = """<div class="current-events-main vevent" id="2026_October_15">
<div class="current-events-content description">
<p><b>Disasters and accidents</b></p>
<ul><li>Wildfires in Highforest<ul><li>Two people died near Lakeview.
<a class="external text" href="https://unlisted.example/wildfire">(Publisher)</a>
<a class="external text" href="https://another.example/report">(Other)</a>
</li></ul></li></ul>
<p><b>Armed conflicts and attacks</b></p>
<ul><li>A Typhoon fighter aircraft was shot down.
<a class="external text" href="https://war.example/story">(Source)</a></li></ul>
</div></div>"""


def partition(provider, now=NOW, cursor=""):
    return CollectionPartition(
        provider.source_id,
        provider.queries[0],
        now,
        now + timedelta(hours=6),
        cursor=cursor,
    )


def payload(html=HTML, title="Portal:Current events/October 2026"):
    return {"parse": {"title": title, "revid": 123456, "text": html}}


async def test_citations_keep_index_provenance_without_promoting_summary_or_date():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        page = await provider.fetch_page(partition(provider))
    assert len(page.leads) == 2
    assert {lead.canonical_url for lead in page.leads} == {
        "https://unlisted.example/wildfire",
        "https://another.example/report",
    }
    for lead in page.leads:
        assert lead.title == "Article title unavailable"
        assert (
            lead.published_at is None
            and lead.updated_at is None
            and lead.indexed_at is None
        )
        assert "Wildfires" in lead.discovery_hint and "Lakeview" in lead.discovery_hint
        assert "123456" in lead.external_id and "2026-10-15" in lead.external_id
        assert "en.wikipedia.org" in lead.external_id
    assert not page.articles and page.requested_start is None
    assert page.saturated and page.next_cursor == "1"
    assert any("editorial" in n for n in page.notices)
    request = requests[0]
    assert request.url.params["maxlag"] == "5"
    assert request.url.params["page"] == "Portal:Current events/October 2026"
    assert "DisasterMonitorBot" in request.headers["User-Agent"]
    assert "github.com/FearOfTheSea/DisasterMonitor" in request.headers["User-Agent"]


@pytest.mark.parametrize(
    "hazard",
    [
        "Bushfires",
        "Mudslides",
        "Volcanic eruptions",
        "Tropical storms",
        "Quakes",
        "Inundations",
    ],
)
async def test_citation_filter_uses_the_supported_hazard_vocabulary(hazard):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=payload(HTML.replace("Wildfires", hazard))
            )
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        page = await provider.fetch_page(partition(provider))
    assert len(page.leads) == 2


@pytest.mark.parametrize(
    "context",
    [
        "An open-pit gold mine collapses, killing several workers.",
        "Workers were killed in the collapse of a quarry.",
        "A mine cave-in buries workers after heavy rainfall.",
    ],
)
async def test_ground_collapse_citations_are_acquired_for_publisher_assessment(context):
    html = HTML.replace("Wildfires in Highforest", context)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload(html))
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        page = await provider.fetch_page(partition(provider))
    assert len(page.leads) == 2
    assert not page.articles
    assert all(lead.published_at is None for lead in page.leads)


@pytest.mark.parametrize(
    "context", ["A bridge collapses.", "A coal mine explosion kills workers."]
)
async def test_other_accidents_are_not_ground_collapse_leads(context):
    html = HTML.replace("Wildfires in Highforest", context)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload(html))
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        page = await provider.fetch_page(partition(provider))
    assert not page.leads


async def test_three_month_cursor_handles_short_february_and_stops():
    pages = []

    def respond(request):
        title = request.url.params["page"]
        pages.append(title)
        day = {
            "March": "2026_March_1",
            "February": "2026_February_28",
            "January": "2026_January_31",
        }
        name = title.split("/")[-1].split()[0]
        return httpx.Response(
            200, json=payload(HTML.replace("2026_October_15", day[name]), title)
        )

    now = datetime(2026, 3, 1, tzinfo=UTC)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        current = partition(provider, now)
        for expected in ("1", "2", None):
            page = await provider.fetch_page(current)
            assert page.next_cursor == expected
            if expected:
                current = replace(current, cursor=expected)
    assert pages == [
        "Portal:Current events/March 2026",
        "Portal:Current events/February 2026",
        "Portal:Current events/January 2026",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://unsafe.example/report",
        "javascript:alert(1)",
        "https://user:secret@unsafe.example/report",
        "https://unsafe.example:444/report",
        "https://unsafe.example/report#fragment",
        "/wiki/Wildfire",
        "https://en.wikipedia.org/wiki/Wildfire",
    ],
)
async def test_unsafe_and_internal_links_do_not_become_publisher_leads(url):
    html = HTML.replace("https://unlisted.example/wildfire", url).replace(
        '<a class="external text" href="https://another.example/report">(Other)</a>', ""
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload(html))
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        page = await provider.fetch_page(partition(provider))
    assert not page.leads


async def test_missing_dated_structure_is_a_failure_instead_of_empty_success():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload("<p>Access challenge</p>"))
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        with pytest.raises(CollectionProviderError, match="dated"):
            await provider.fetch_page(partition(provider))


@pytest.mark.parametrize("cursor", ["https://unsafe.example/next", "3", "-1", "01"])
async def test_invalid_continuation_never_makes_a_request(cursor):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (
                requests.append(request) or httpx.Response(200, json=payload())
            )
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        with pytest.raises(CollectionProviderError, match="continuation"):
            await provider.fetch_page(partition(provider, cursor=cursor))
    assert requests == []


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": "maxlag", "info": "busy"}},
        {"error": {"code": "ratelimited", "info": "busy"}},
    ],
)
async def test_busy_api_payload_is_one_rate_limited_attempt(body):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json=body)
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        with pytest.raises(CollectionProviderError) as error:
            await provider.fetch_page(partition(provider))
    assert error.value.outcome == "rate_limited"
    assert len(requests) == 1


async def test_citation_capacity_refuses_the_whole_page_instead_of_dropping_leads():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload())
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0, maximum_citations=1
        )
        with pytest.raises(CollectionProviderError) as error:
            await provider.fetch_page(partition(provider))
    assert error.value.outcome == "capacity_exhausted"
    assert "not acknowledged" in error.value.detail


@pytest.mark.parametrize(
    "data",
    [
        {"parse": {"title": "Other page", "revid": 123, "text": HTML}},
        {
            "parse": {
                "title": "Portal:Current events/October 2026",
                "revid": True,
                "text": HTML,
            }
        },
        {
            "parse": {
                "title": "Portal:Current events/October 2026",
                "revid": 123,
                "text": {},
            }
        },
        {"error": {"code": "missingtitle"}},
    ],
)
async def test_invalid_api_identity_and_metadata_are_failures(data):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        with pytest.raises(CollectionProviderError) as error:
            await provider.fetch_page(partition(provider))
    assert error.value.outcome == "invalid_response"


async def test_outside_index_days_cannot_add_citations_to_the_recent_snapshot():
    outside = (
        HTML.replace("2026_October_15", "2026_October_21")
        .replace("unlisted.example", "future.example")
        .replace("another.example", "future-other.example")
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload(HTML + outside))
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        page = await provider.fetch_page(partition(provider))
    assert len(page.leads) == 2
    assert not any("future" in lead.canonical_url for lead in page.leads)


async def test_index_hint_never_becomes_a_publisher_title_date_or_claim():
    from disaster_monitor.domain.discovery import ReportingInterval, assess_article
    from disaster_monitor.infrastructure.news.collection_providers import (
        PublicCollectionArticleReader,
    )

    class Reader:
        async def read(self, url):
            return """<head><meta property="og:title" content="Transport update">
            <meta property="og:site_name" content="Regional Daily">
            <meta property="article:published_time" content="2026-10-19T12:00:00Z">
            </head><article><p>Services operated normally.</p></article>"""

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload())
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        page = await provider.fetch_page(partition(provider))
    article = await PublicCollectionArticleReader(reader=Reader()).retrieve(
        page.leads[0]
    )
    assert article.source.title == "Transport update"
    assert article.source.publisher == "Regional Daily"
    assert article.source.published_at == datetime(2026, 10, 19, 12, tzinfo=UTC)
    assert article.indexed_at is None and article.event_time is None
    assert "died" not in article.text
    assessed = assess_article(article, ReportingInterval.at_start(30, NOW))
    assert not assessed.mentions and not assessed.fatality_evidence


async def test_shared_index_work_and_search_hints_survive_restart(tmp_path):
    from uuid import uuid4

    from disaster_monitor.application.incidents.collection_planning import (
        plan_collection,
    )
    from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
    from disaster_monitor.infrastructure.operations.sqlite_collection import (
        SQLiteCollectionJournal,
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload())
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        one = plan_collection(
            ReportingInterval.at_start(1, NOW), (provider,), observed_at=NOW
        )
        month = plan_collection(
            ReportingInterval.at_start(30, NOW), (provider,), observed_at=NOW
        )
        assert len(one) == len(provider.queries) and one == month
        # This restart scenario follows the monthly index's month cursor.
        one = tuple(p for p in one if p.query == "current-events-citations")
        assert len(one) == 1
        path = tmp_path / "index.sqlite"
        store = SQLiteCollectionJournal(path)
        scans = [
            DiscoveryRun(str(uuid4()), ReportingInterval.at_start(days, NOW))
            for days in (1, 30)
        ]
        for scan in scans:
            await store.attach(scan, one, now=NOW, budget=1)
        claimed = await store.claim("search", "worker", now=NOW)
        page = await provider.fetch_page(claimed.partition)
        assert await store.commit_page(claimed, page, now=NOW)
        await store.finish_pass(now=NOW)
        restarted = SQLiteCollectionJournal(path)
        for scan in scans:
            saved = await restarted.snapshot(scan.scan_id, now=NOW)
            assert {lead.canonical_url: lead for lead in saved.leads} == {
                lead.canonical_url: lead for lead in page.leads
            }
            assert saved.progress.pages_acquired == 1
        await restarted.continue_scan(scans[0].scan_id, now=NOW, budget=1)
        next_month = await restarted.claim("search", "new-worker", now=NOW)
        assert next_month.partition.cursor == "1"
