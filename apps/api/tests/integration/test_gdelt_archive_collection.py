"""Public archive metadata supplies bounded leads, never article facts."""

import gzip
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.domain.collection import (
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.infrastructure.news.gdelt_archive import (
    GdeltArchiveCollectionProvider,
)

NOW = datetime(2026, 10, 22, 12, 50, tzinfo=UTC)
START = NOW.replace(minute=30)
END = NOW.replace(minute=45)


def partition(provider, **changes):
    return replace(
        CollectionPartition(provider.source_id, provider.queries[0], START, END),
        **changes,
    )


def record(**changes):
    return dict(
        ID=1,
        date="2026-10-22T12:31:00.000Z",
        lang="en",
        title="Seven people drowned after floods hit a mine",
        url="https://regional.example/flood",
        img="https://images.example/unattributed.jpg",
        **changes,
    )


def payload(rows):
    return "\n".join(json.dumps(row) for row in rows).encode()


async def test_archive_keeps_native_headline_and_index_clock_as_lead_only():
    requests = []
    data = payload(
        [
            record(),
            {
                **record(),
                "ID": 2,
                "title": "Football team wins cup",
                "url": "https://sport.example/result",
            },
        ]
    )

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=gzip.compress(data))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        page = await provider.fetch_page(partition(provider))
    assert requests[0].url.path.endswith("/20261022123100.toc.json.gz")
    (lead,) = page.leads
    assert lead.published_at is None and lead.updated_at is None
    assert lead.indexed_at == START + timedelta(minutes=1)
    assert lead.search_title == lead.title
    assert lead.canonical_url == "https://regional.example/flood"
    assert lead.publisher == "regional.example"
    assert "20261022123100" in lead.external_id
    assert not page.articles and not page.supplemental
    assert page.next_cursor and page.saturated
    assert any("publication" in notice for notice in page.notices)


async def test_complete_traversal_visits_each_minute_once_without_skipping_404_gaps():
    paths = []
    notices = set()
    requested_windows = set()

    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        part = partition(provider)
        while True:
            page = await provider.fetch_page(part)
            assert not page.leads
            assert any("404" in notice for notice in page.notices)
            notices.update(page.notices)
            requested_windows.add((page.requested_start, page.requested_end))
            if page.next_cursor is None:
                break
            part = replace(part, cursor=page.next_cursor)
    assert len(paths) == len(set(paths)) == 15
    # Scans deduplicate notices by text; a cold traversal must not accumulate
    # thousands of unique gap messages. Page bounds retain each requested minute.
    assert len(notices) == 2
    assert requested_windows == {
        (START + timedelta(minutes=i), START + timedelta(minutes=i + 1))
        for i in range(15)
    }
    assert paths[0].endswith("20261022123100.toc.json.gz")
    assert paths[1].endswith("20261022123200.toc.json.gz")
    assert {path.rsplit("/", 1)[1][:14] for path in paths} == {
        (START + timedelta(minutes=i)).strftime("%Y%m%d%H%M00") for i in range(15)
    }


async def test_cursor_freezes_index_cutoff_across_later_resume():
    paths = []

    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        part = partition(provider, end=NOW + timedelta(hours=1))
        first = await provider.fetch_page(part)
        resumed = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW + timedelta(hours=1)
        )
        part = replace(part, cursor=first.next_cursor)
        while True:
            page = await resumed.fetch_page(part)
            if page.next_cursor is None:
                break
            part = replace(part, cursor=page.next_cursor)
    assert len(paths) == 16  # Inclusive 12:30 through the safe 12:45 index minute.
    assert all("2026102213" not in path for path in paths)


@pytest.mark.parametrize(
    "cursor",
    [
        "https://unsafe.example/file",
        "20261022124600:0",
        "20261021123100:0",
        "20261022124400:99999",
        "junk:1",
    ],
)
async def test_invalid_or_future_cursor_is_rejected_before_request(cursor):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(404)
        )
    ) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        with pytest.raises(CollectionProviderError, match="continuation"):
            await provider.fetch_page(partition(provider, cursor=cursor))
    assert not requests


@pytest.mark.parametrize(
    "status,outcome",
    [(429, "rate_limited"), (403, "access_refused"), (503, "transport_failed")],
)
async def test_archive_failures_are_not_treated_as_empty_minutes(status, outcome):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, headers={"Retry-After": "60"})
        )
    ) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        with pytest.raises(CollectionProviderError) as error:
            await provider.fetch_page(partition(provider))
    assert error.value.outcome == outcome
    assert error.value.retry_after_seconds == 60


@pytest.mark.parametrize("body", [b"{broken", b"[]", b"\xff", gzip.compress(b"broken")])
async def test_malformed_archive_is_not_acknowledged(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _, body=body: httpx.Response(200, content=body)
        )
    ) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        with pytest.raises(CollectionProviderError, match="archive"):
            await provider.fetch_page(partition(provider))


async def test_gzip_and_plain_ndjson_are_supported_but_expansion_is_bounded():
    for compressed in (False, True):
        body = payload([record()])
        body = gzip.compress(body) if compressed else body
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _, body=body: httpx.Response(200, content=body)
            )
        ) as client:
            provider = GdeltArchiveCollectionProvider(
                client=client, minimum_interval=0, clock=lambda: NOW
            )
            assert len((await provider.fetch_page(partition(provider))).leads) == 1
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=gzip.compress(b"x" * 10001))
        )
    ) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client,
            minimum_interval=0,
            clock=lambda: NOW,
            maximum_decoded_bytes=10000,
        )
        with pytest.raises(CollectionProviderError, match="byte"):
            await provider.fetch_page(partition(provider))


async def test_unsafe_links_wrong_index_clock_and_duplicates_do_not_supply_leads():
    rows = [
        record(),
        {**record(), "ID": 2},
        {**record(), "ID": 3, "url": "http://regional.example/flood"},
        {**record(), "ID": 4, "url": "https://127.0.0.1/private"},
        {**record(), "ID": 5, "date": "2026-10-22T12:32:00Z"},
        {**record(), "ID": 6, "url": "https://other.example/a", "title": ""},
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=payload(rows))
        )
    ) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        page = await provider.fetch_page(partition(provider))
    assert len(page.leads) == 1
    assert any("4 invalid" in notice for notice in page.notices)


async def test_durable_archive_cursor_and_lead_survive_restart(tmp_path):
    from uuid import uuid4

    from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
    from disaster_monitor.infrastructure.operations.sqlite_collection import (
        SQLiteCollectionJournal,
    )

    path = tmp_path / "archive.sqlite"
    journal = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=payload([record()]))
        )
    ) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        await journal.attach(run, (partition(provider),), now=NOW, budget=1)
        work = await journal.claim("search", "first", now=NOW)
        assert work is not None
        page = await provider.fetch_page(work.partition)
        assert await journal.commit_page(work, page, now=NOW)
        await journal.finish_pass(now=NOW)
        restarted = SQLiteCollectionJournal(path)
        await restarted.continue_scan(run.scan_id, now=NOW, budget=1)
        resumed = await restarted.claim("search", "second", now=NOW)
        assert resumed is not None and resumed.partition.cursor == page.next_cursor
        snapshot = await restarted.snapshot(run.scan_id, now=NOW)
        assert snapshot.leads == page.leads
        assert snapshot.leads[0].published_at is None
        assert snapshot.progress.pages_acquired == 1


async def test_normal_scan_uses_publisher_publication_instead_of_archive_clock(
    tmp_path,
):
    from disaster_monitor.application.incidents.resumable_discovery import (
        ResumableDiscovery,
    )
    from disaster_monitor.domain.discovery import DiscoveryArticle
    from disaster_monitor.domain.evidence_types import SourceReference
    from disaster_monitor.infrastructure.operations.sqlite_collection import (
        SQLiteCollectionJournal,
    )

    def respond(request):
        name = request.url.path.rsplit("/", 1)[1].split(".")[0]
        stamp = datetime.strptime(name, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        return httpx.Response(
            200, content=payload([{**record(), "date": stamp.isoformat()}])
        )

    class Reader:
        async def retrieve(self, lead):
            return DiscoveryArticle(
                SourceReference(
                    "publisher",
                    "Regional Daily",
                    "Flood killed seven",
                    lead.canonical_url,
                    NOW - timedelta(days=2),
                    None,
                    NOW,
                ),
                "Seven people drowned after a flood struck the mine.",
            )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GdeltArchiveCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        service = ResumableDiscovery(
            (provider,),
            Reader(),
            SQLiteCollectionJournal(tmp_path / "journal.sqlite"),
            clock=lambda: NOW,
            page_budget=1,
        )
        try:
            narrow = await service.start(1)
            await service.wait(narrow.scan_id)
            wide = await service.start(7)
            await service.wait(wide.scan_id)
            narrow_run = await service.get(narrow.scan_id)
            assert narrow_run.reports and all(
                report.eligibility == "outside_interval"
                for report in narrow_run.reports
            )
            assert not narrow_run.events
            reports = (await service.get(wide.scan_id)).reports
            assert reports and reports[
                0
            ].article.source.published_at == NOW - timedelta(days=2)
            assert any(
                claim.fact.category == "fatalities" and claim.fact.value == "Seven"
                for report in reports
                for mention in report.mentions
                for claim in mention.claims
            )
        finally:
            await service.aclose()
