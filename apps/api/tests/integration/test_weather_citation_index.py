"""Annual weather timelines supply bounded publisher leads, never event evidence."""

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

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
QUERY = "weather-timeline-citations"


def markup(entries, references=None, month="October"):
    references = references or (
        '<li id="cite_note-a"><a href="#cite_ref-a">Up</a>'
        '<a class="external text" href="https://daily.example/report">Daily</a></li>'
    )
    return (
        '<h2 id="Statistics">Statistics</h2>'
        "<ul><li>October 14 – Floods killed nine people."
        '<a href="#cite_note-a">[a]</a></li></ul>'
        f'<h2 id="Timeline">Timeline</h2><h3 id="{month}">{month}</h3>'
        f'<ul>{entries}</ul><h2 id="References">References</h2><ol>{references}</ol>'
    )


def entry(text="October 14 – Floods struck Lakeview. Nine people died.", ref="a"):
    return f'<li>{text}<sup><a href="#cite_note-{ref}">[ref]</a></sup></li>'


async def fetch(html, *, now=NOW, cursor="", maximum_citations=1000):
    requests = []
    years = [now.year]
    oldest = (now.date() - timedelta(days=31)).year
    if oldest != now.year:
        years.append(oldest)
    title = f"Weather of {years[int(cursor or '0')]}"

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, json={"parse": {"title": title, "revid": 123456, "text": html}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0, maximum_citations=maximum_citations
        )
        page = await provider.fetch_page(
            CollectionPartition(
                provider.source_id, QUERY, now, now + timedelta(hours=6), cursor=cursor
            )
        )
    return page, requests


async def test_timeline_references_supply_only_public_publisher_citation_leads():
    page, requests = await fetch(markup(entry()))
    (lead,) = page.leads
    assert lead.canonical_url == "https://daily.example/report"
    assert lead.title == "Article title unavailable"
    assert "Floods struck Lakeview" in lead.discovery_hint
    assert "123456" in lead.external_id and "2026-10-14" in lead.external_id
    assert (
        lead.published_at is None
        and lead.updated_at is None
        and lead.indexed_at is None
    )
    assert not page.articles and not page.supplemental
    assert page.requested_start is None and page.requested_end is None
    assert page.saturated and page.next_cursor is None
    assert requests[0].url.params["page"] == "Weather of 2026"
    assert requests[0].url.params["maxlag"] == "5"
    assert "DisasterMonitorBot" in requests[0].headers["User-Agent"]


@pytest.mark.parametrize(
    "date_text",
    [
        "October 14",
        "October 14–15",
        "October 14-15",
        "October 14 — 15",
    ],
)
async def test_explicit_timeline_days_and_ranges_remain_search_only(date_text):
    page, _ = await fetch(
        markup(entry(f"{date_text} – Grass fires killed two people."))
    )
    assert len(page.leads) == 1
    assert page.leads[0].published_at is None


async def test_range_that_overlaps_the_lookback_can_supply_a_lead():
    page, _ = await fetch(
        markup(entry("September 18–22 – Floods struck Lakeview."), month="September")
    )
    assert len(page.leads) == 1


async def test_cross_month_range_can_overlap_a_later_lookback_boundary():
    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    page, _ = await fetch(
        markup(
            entry("October 8–November 2 – Floods struck Lakeview."), month="October"
        ),
        now=now,
    )
    assert len(page.leads) == 1


async def test_statistics_and_post_timeline_lists_cannot_supply_citation_leads():
    html = markup(entry("October 1 – A heatwave.")).replace(
        '<h2 id="References">References</h2>',
        '<h2 id="Other">Other</h2><ul>' + entry() + "</ul>"
        '<h2 id="References">References</h2>',
    )
    page, _ = await fetch(html)
    assert not page.leads


@pytest.mark.parametrize(
    "text",
    [
        "October 21 – Floods struck Lakeview.",
        "September 1 – Floods struck Lakeview.",
        "October 32 – Floods struck Lakeview.",
        "October 15–14 – Floods struck Lakeview.",
        "October 14 – A heatwave affected Lakeview.",
        "By October 14 floods affected Lakeview.",
    ],
)
async def test_outside_window_invalid_dates_and_unsupported_hazards_supply_no_leads(
    text,
):
    # A valid non-hazard dated entry proves the timeline structure is still present.
    page, _ = await fetch(markup(entry(text) + entry("October 1 – A heatwave.")))
    assert not page.leads


async def test_modern_heading_wrappers_and_reference_reuse_do_not_duplicate_leads():
    html = (
        markup(entry() + entry("October 15 – Flooding continued."))
        .replace(
            '<h2 id="Timeline">Timeline</h2>',
            '<div class="mw-heading"><h2><span id="Timeline">Timeline</span>'
            "</h2></div>",
        )
        .replace(
            '<h3 id="October">October</h3>',
            '<div class="mw-heading"><h3><span id="October">October</span></h3></div>',
        )
    )
    page, _ = await fetch(html)
    assert len(page.leads) == 1


async def test_unsafe_internal_and_unresolved_references_never_supply_publisher_urls():
    references = (
        '<li id="cite_note-a"><a class="external" href="http://unsafe.example/a">A</a>'
        '<a class="external" href="https://en.wikipedia.org/wiki/Flood">B</a>'
        '<a class="external" href="https://user:secret@daily.example/a">C</a>'
        '<a class="external" href="https://daily.example:8080/a">D</a></li>'
    )
    page, _ = await fetch(markup(entry() + entry(ref="missing"), references))
    assert not page.leads
    assert any("excluded" in notice for notice in page.notices)


async def test_duplicate_reference_ids_are_ambiguous_and_cannot_supply_a_lead():
    references = "".join(
        '<li id="cite_note-a"><a class="external" '
        f'href="https://{host}/report">Daily</a></li>'
        for host in ("first.example", "second.example")
    )
    page, _ = await fetch(markup(entry(), references))
    assert not page.leads


async def test_publisher_homepage_citations_do_not_become_article_retrievals():
    references = (
        '<li id="cite_note-a"><a class="external" href="https://daily.example/">A</a>'
        '<a class="external" href="https://other.example">B</a></li>'
    )
    page, _ = await fetch(markup(entry(), references))
    assert not page.leads


async def test_annual_citation_limit_fails_the_whole_page_instead_of_truncating():
    references = (
        '<li id="cite_note-a"><a class="external" href="https://first.example/a">A</a>'
        '<a class="external" href="https://second.example/b">B</a></li>'
    )
    with pytest.raises(CollectionProviderError) as failure:
        await fetch(markup(entry(), references), maximum_citations=1)
    assert failure.value.outcome == "capacity_exhausted"


@pytest.mark.parametrize(
    "html",
    [
        "<h2>Statistics</h2><ul><li>Floods killed nine people.</li></ul>",
        '<h2 id="Timeline">Timeline</h2><h3>October</h3>'
        "<ul><li>Undated floods.</li></ul>",
    ],
)
async def test_missing_dated_timeline_structure_is_failure_instead_of_empty_success(
    html,
):
    with pytest.raises(CollectionProviderError) as failure:
        await fetch(html)
    assert failure.value.outcome == "invalid_response"


async def test_year_boundary_uses_two_bounded_pages_without_changing_provider_scope():
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)
    current, first = await fetch(
        markup(entry("January 2 – Floods struck Lakeview."), month="January"), now=now
    )
    previous, second = await fetch(
        markup(entry("December 20 – Floods struck Lakeview."), month="December"),
        now=now,
        cursor="1",
    )
    assert current.next_cursor == "1" and previous.next_cursor is None
    assert first[0].url.params["page"] == "Weather of 2026"
    assert second[0].url.params["page"] == "Weather of 2025"
    assert len(current.leads) == len(previous.leads) == 1


async def test_compatible_scan_windows_share_annual_index_work_and_retained_hints(
    tmp_path,
):
    from uuid import uuid4

    from disaster_monitor.application.incidents.collection_planning import (
        plan_collection,
    )
    from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
    from disaster_monitor.infrastructure.operations.sqlite_collection import (
        SQLiteCollectionJournal,
    )

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "parse": {
                    "title": "Weather of 2026",
                    "revid": 123456,
                    "text": markup(entry()),
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        runs = [
            DiscoveryRun(str(uuid4()), ReportingInterval.at_start(days, NOW))
            for days in (1, 30)
        ]
        store = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
        for run in runs:
            partitions = tuple(
                p
                for p in plan_collection(run.interval, (provider,), observed_at=NOW)
                if p.query == QUERY
            )
            await store.attach(run, partitions, now=NOW, budget=10)
        work = await store.claim("search", "one-worker", now=NOW)
        page = await provider.fetch_page(work.partition)
        await store.commit_page(work, page, now=NOW)
        assert await store.claim("search", "another-worker", now=NOW) is None
        restarted = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
        for run in runs:
            saved = await restarted.snapshot(run.scan_id, now=NOW)
            assert saved.leads == page.leads
            assert saved.progress.pages_acquired == 1
        assert len(calls) == 1


async def test_monthly_refusal_cooldown_also_blocks_annual_query_without_extra_request(
    tmp_path,
):
    from disaster_monitor.application.incidents.resumable_discovery import (
        ResumableDiscovery,
    )
    from disaster_monitor.infrastructure.operations.sqlite_collection import (
        SQLiteCollectionJournal,
    )

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "1800"})

    class Reader:
        async def retrieve(self, lead):
            raise AssertionError("A refused index must not create article work.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = WikipediaCitationCollectionProvider(
            client=client, minimum_interval=0
        )
        store = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
        runtime = ResumableDiscovery((provider,), Reader(), store, clock=lambda: NOW)
        try:
            run = await runtime.start(30)
            await runtime.wait(run.scan_id)
            progress = (await store.read(run.scan_id)).collection
            assert progress.searches_pending == 2
            assert progress.retry_at >= NOW + timedelta(seconds=1800)
            assert len(calls) == 1
        finally:
            await runtime.aclose()
