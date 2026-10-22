"""Annual quake tables provide dated search leads without promoting table facts."""

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

NOW = datetime(2026, 10, 20, tzinfo=UTC)
HTML = """<h2 id="By_magnitude">By magnitude</h2>
<table><tr><th>Date</th><th>Country and location</th><th>Notes</th></tr>
<tr><td>15</td><td>Elsewhere</td><td>Earthquake killed three
<a href="#cite_note-stats">[1]</a></td></tr></table>
<h2 id="By_month">By month</h2><h3 id="September">September</h3>
<table class="wikitable"><tr><th>Date</th><th>Country and location</th><th>M</th>
<th>Depth (km)</th><th>MMI</th><th>Notes</th><th>Casualties</th></tr>
<tr><th>Dead</th><th>Injured</th></tr>
<tr><td>10</td><td>Oldcountry</td><td>5.1</td><td>10</td><td>V</td>
<td>One killed<a href="#cite_note-old">[2]</a></td><td>1</td><td>-</td></tr>
<tr><td>28<a href="#cite_note-monitor">[3]</a></td><td>Newcountry</td>
<td>5.1</td><td>10</td><td>V</td><td>Two killed in rockfall
<a href="#cite_note-news">[4]</a></td><td>2</td><td>-</td></tr></table>
<h3><span id="October">October</span></h3>
<table><tr><th>Date</th><th>Country and location</th><th>M</th>
<th>Depth (km)</th><th>MMI</th><th>Notes</th><th>Casualties</th></tr>
<tr><th>Dead</th><th>Injured</th></tr>
<tr><td>3</td><td>Highland</td><td>5.9</td><td>20</td><td>VI</td>
<td>One person killed<a href="#cite_note-local">[5]</a>
<a href="#cite_note-missing">[6]</a><a href="#cite_note-unsafe">[7]</a>
<a href="/wiki/Some_earthquake">Internal event</a></td><td>1</td><td>-</td></tr>
<tr><td>21</td><td>Futureland</td><td>5.9</td><td>20</td><td>VI</td>
<td>One killed<a href="#cite_note-future">[8]</a></td><td>1</td><td>-</td></tr></table>
<h2 id="References">References</h2><ol>
<li id="cite_note-stats"><a class="external text" href="https://stats.example/story">Stats</a></li>
<li id="cite_note-old"><a class="external text" href="https://old.example/story">Old</a></li>
<li id="cite_note-monitor"><a class="external text" href="https://monitor.example/event">Monitor</a></li>
<li id="cite_note-news"><a class="external text" href="https://news.example/story">Daily</a></li>
<li id="cite_note-local"><a class="external text" href="https://local.example/story">Local</a></li>
<li id="cite_note-unsafe"><a class="external text" href="http://127.0.0.1/story">Unsafe</a></li>
<li id="cite_note-future"><a class="external text" href="https://future.example/story">Future</a></li></ol>"""


def partition(cursor="", now=NOW):
    return CollectionPartition(
        "wikipedia-citation-discovery",
        "earthquake-timeline-citations",
        now,
        now + timedelta(hours=6),
        cursor=cursor,
    )


async def test_annual_quake_index_resolves_only_recent_dated_row_references():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "parse": {
                    "title": "List of earthquakes in 2026",
                    "revid": 12345,
                    "text": HTML,
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        assert "earthquake-timeline-citations" in provider.queries
        page = await provider.fetch_page(partition())
    assert {lead.canonical_url for lead in page.leads} == {
        "https://monitor.example/event",
        "https://news.example/story",
        "https://local.example/story",
    }
    for lead in page.leads:
        assert "Earthquake editorial index" in lead.discovery_hint
        assert (
            lead.published_at is None
            and lead.updated_at is None
            and lead.indexed_at is None
        )
        assert "12345" in lead.external_id
        assert lead.title == "Article title unavailable"
    assert not page.articles and page.requested_start is None and page.saturated
    assert page.next_cursor is None
    assert any("2" in n and "excluded" in n for n in page.notices)
    assert requests[0].url.params["page"] == "List of earthquakes in 2026"


@pytest.mark.parametrize(
    "anchor,expected",
    [
        (
            '"Un residente falleció durante el terremoto"',
            '"Un residente falleció durante el terremoto"',
        ),
        ("Archived from the original on October 3", None),
        ("Local Daily", None),
    ],
)
def test_citation_headline_is_a_search_hint_without_promoting_index_facts(
    anchor, expected
):
    from datetime import date

    from disaster_monitor.infrastructure.news.wikipedia_citations import (
        parse_earthquake_citations,
    )

    leads, _ = parse_earthquake_citations(
        HTML.replace(">Local</a>", f">{anchor}</a>"),
        year=2026,
        earliest=date(2026, 9, 20),
        latest=date(2026, 10, 20),
        revision=12345,
    )
    lead = next(
        item for item in leads if item.canonical_url == "https://local.example/story"
    )
    assert lead.search_title == expected
    assert lead.title == "Article title unavailable"
    assert lead.published_at is None and lead.indexed_at is None
    assert (
        next(
            item for item in leads if item.canonical_url.endswith("/event")
        ).search_title
        is None
    )


@pytest.mark.parametrize(
    "body",
    [
        HTML.replace('id="By_month"', 'id="Other"'),
        HTML.replace("<th>Date</th>", "<th>Unrecognized</th>"),
    ],
)
async def test_unrecognized_quake_calendar_is_unavailable_instead_of_empty_success(
    body,
):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "parse": {
                        "title": "List of earthquakes in 2026",
                        "revid": 12345,
                        "text": body,
                    }
                },
            )
        )
    ) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        with pytest.raises(CollectionProviderError, match="[Cc]itation|[Qq]uake"):
            await provider.fetch_page(partition())


async def test_quake_index_continues_to_previous_year_only_across_new_year():
    titles = []

    def respond(request):
        title = request.url.params["page"]
        titles.append(title)
        return httpx.Response(
            200, json={"parse": {"title": title, "revid": 12345, "text": HTML}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        now = datetime(2027, 1, 10, tzinfo=UTC)
        first = await provider.fetch_page(partition(now=now))
        assert first.next_cursor == "1"
        second = await provider.fetch_page(partition(cursor="1", now=now))
        assert second.next_cursor is None
    assert titles == ["List of earthquakes in 2027", "List of earthquakes in 2026"]
