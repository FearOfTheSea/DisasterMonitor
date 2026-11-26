from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import (
    DiscoveryRun,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_providers import (
    PublicCollectionArticleReader,
    ReliefWebCollectionProvider,
)
from disaster_monitor.infrastructure.news.public_documents import PublicDocumentReader
from disaster_monitor.infrastructure.news.publisher_pdf import extract_publisher_pdf
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
URL = "https://publisher.example/reports/october-16.pdf"


def report_pdf(*lines: str) -> bytes:
    writer = PdfWriter()
    writer.add_metadata(
        {"/CreationDate": "D:20261016120000Z", "/Title": "Flood report"}
    )
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    contents = DecodedStreamObject()
    commands = "\n".join(f"({line}) Tj T*" for line in lines)
    contents.set_data(f"BT /F1 12 Tf 16 TL 48 740 Td\n{commands}\nET".encode())
    page[NameObject("/Contents")] = contents
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("date_lines", "eligible"),
    [
        (("Publishing date: 16 October 2026",), True),
        (("Published: 2026-10-16T08:15:00Z",), True),
        (("DREF Published:", "2026-10-16"), True),
        (("Publishing date: October 2026",), False),
        (("Report updated: 2026-10-16",), False),
        (("Previously published:", "2026-10-16"), False),
        (("Published: 2026-10-16", "Published: 2026-10-17"), False),
        ((), False),
    ],
)
async def test_pdf_reports_use_explicit_publisher_clock(date_lines, eligible):
    body = report_pdf(
        "Flood report", *date_lines, "Floods killed ", "two people in Riverton."
    )

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            headers={
                "content-type": "application/pdf",
                "last-modified": "Fri, 16 Oct 2026 12:00:00 GMT",
            },
            content=body,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicCollectionArticleReader(
            reader=PublicDocumentReader(
                client=client, resolver=lambda host: ("93.184.216.34",)
            )
        )
        article = await reader.retrieve(
            NewsFeedItem("indexed", "Publisher", "Report", URL, NOW, NOW, NOW)
        )
    assert article.source.canonical_url == URL
    assert article.source.title == "Flood report"
    assert article.source.updated_at is None
    assert "Floods killed two people in Riverton." in article.text
    report = assess_article(article, ReportingInterval.at_start(3, NOW))
    assert report.eligibility == ("eligible" if eligible else "unknown_publication")
    if eligible:
        assert any(
            claim.fact.category == "fatalities" and claim.fact.value == "two"
            for mention in report.mentions
            for claim in mention.claims
        )
    else:
        assert article.source.published_at is None


@pytest.mark.parametrize(
    ("headers", "body", "message"),
    [
        ({"content-type": "application/pdf"}, b"not a PDF", "lacks a PDF header"),
        ({"content-type": "application/pdf"}, b"%PDF-1.7\n", "could not be read"),
        (
            {"content-type": "application/pdf", "content-length": "12582913"},
            b"",
            "exceeds byte limit",
        ),
    ],
)
async def test_pdf_transport_and_parse_failures_remain_publisher_failures(
    headers, body, message
):
    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers=headers, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicCollectionArticleReader(
            reader=PublicDocumentReader(
                client=client, resolver=lambda host: ("93.184.216.34",)
            )
        )
        with pytest.raises(CollectionProviderError, match=message) as caught:
            await reader.retrieve(
                NewsFeedItem("indexed", "Publisher", "Report", URL, NOW, None, NOW)
            )
    assert caught.value.outcome == "article_unavailable"


async def test_pdf_text_limit_drops_partial_source_line():
    complete_sentence = "Floods killed two people in Riverton."
    oversized = report_pdf(complete_sentence, "x" * 21_000)

    extracted = await extract_publisher_pdf(oversized)
    assert extracted.text == complete_sentence


@pytest.mark.parametrize("edition_day", [None, "2026-10-16"])
async def test_report_links_use_one_shared_publisher_queue_and_own_date(
    tmp_path,
    edition_day,
):
    release = "https://publisher.example/release"
    mirror = "https://second.example/release"
    report_url = "https://reports.example/edition.pdf"
    unrelated = "https://reports.example/unrelated.pdf"
    imprint = (f"Published: {edition_day}",) if edition_day else ()
    pdf = report_pdf("Flood report", *imprint, "Floods killed two people in Riverton.")
    fetched = []

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        fetched.append((request.headers["host"], request.url.path))
        if request.url.path == "/edition.pdf":
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=pdf,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=f"""
        <meta property="article:published_time" content="2026-10-17T09:00:00Z">
        <article><h1>Flood recovery report</h1>
        <p>The full edition describes regional flooding.</p>
        <a href="{report_url}">Download full report</a>
        <a href="{report_url}#page=2">Download full report</a>
        <a href="https://127.0.0.1/internal.pdf">Full report</a>
        <a rel="nofollow" href="https://reports.example/nofollow.pdf">Full report</a>
        <aside><a href="{unrelated}">Full report</a></aside></article>
        """,
        )

    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path)
    run = DiscoveryRun("scan", ReportingInterval.at_start(3, NOW))
    partition = CollectionPartition("index", "flood report", run.interval.start, NOW)
    await journal.attach(run, (partition,), now=NOW, budget=1)
    search = await journal.claim("search", "index", now=NOW)
    leads = tuple(
        NewsFeedItem(host, host, "Flood recovery report", link, None, None)
        for host, link in (("Publisher", release), ("Second", mirror))
    )
    assert await journal.commit_page(search, CollectionPage(leads=leads), now=NOW)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicCollectionArticleReader(
            reader=PublicDocumentReader(
                client=client, resolver=lambda host: ("93.184.216.34",)
            )
        )
        for _ in range(3):
            journal = SQLiteCollectionJournal(path)
            work = await journal.claim("retrieve", "publisher", now=NOW)
            assert work is not None
            article = await reader.retrieve(work.lead)
            assert await journal.commit_article(work, article, now=NOW)

    assert (
        await SQLiteCollectionJournal(path).claim("retrieve", "publisher", now=NOW)
        is None
    )
    assert len(fetched) == 3
    assert fetched.count(("reports.example", "/edition.pdf")) == 1
    snapshot = await journal.snapshot(run.scan_id, now=NOW)
    report = next(a for a in snapshot.articles if a.source.canonical_url == report_url)
    assessment = assess_article(report, run.interval)
    if edition_day:
        assert report.source.published_at == datetime(2026, 10, 16, tzinfo=UTC)
        assert assessment.eligibility == "eligible"
    else:
        assert report.source.published_at is None
        assert assessment.eligibility == "unknown_publication"


@pytest.mark.parametrize(
    ("blocked_status", "imprint", "expects_search"),
    [
        (403, None, True),
        (403, "2026-10-16", True),
        (429, None, False),
        (200, None, False),
    ],
)
async def test_linked_pdf_failure_searches_for_an_independent_publisher_once(
    tmp_path,
    blocked_status,
    imprint,
    expects_search,
):
    release = "https://publisher.example/release"
    blocked = "https://reports.example/original.pdf"
    mirror = "https://mirror.example/edition.pdf"
    title = "Riverton River Basin Flood Recovery Assessment"
    date_lines = (f"Published: {imprint}",) if imprint else ()
    pdf = report_pdf(title, *date_lines, "Floods killed two people in Riverton.")
    requests = []
    publisher_requests = []

    class Index:
        source_id = "index"
        queries = ("disaster report",)
        supports_time_filter = True
        supports_alternates = True

        async def fetch_page(self, partition):
            urls = (blocked, mirror) if partition.alternate_for else (release,)
            requests.append(partition)
            return CollectionPage(
                leads=tuple(
                    NewsFeedItem(url, "Index title", title, url, None, None)
                    for url in urls
                )
            )

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        publisher_requests.append(request.url.path)
        if request.url.path == "/release":
            return httpx.Response(
                200,
                text=f"""
                <meta property="og:title" content="{title}">
                <meta property="article:published_time" content="2026-10-17T09:00:00Z">
                <article><h1>{title}</h1>
                <p>The full edition describes regional flooding.</p>
                <a href="{blocked}">Full report</a></article>
                """,
                headers={"content-type": "text/html"},
            )
        if request.url.path == "/original.pdf" and blocked_status != 200:
            return httpx.Response(blocked_status)
        return httpx.Response(
            200, content=pdf, headers={"content-type": "application/pdf"}
        )

    journal = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = ResumableDiscovery(
            (Index(),),
            PublicCollectionArticleReader(
                reader=PublicDocumentReader(
                    client=client, resolver=lambda host: ("93.184.216.34",)
                )
            ),
            journal,
            clock=lambda: NOW,
            pass_seconds=3,
        )
        try:
            run = await service.start(3)
            await service.wait(run.scan_id)
        finally:
            await service.aclose()

    alternate = [part for part in requests if part.alternate_for]
    assert bool(alternate) == expects_search
    assert publisher_requests.count("/original.pdf") == 1
    if expects_search:
        (partition,) = alternate
        assert partition.alternate_for == blocked
        assert partition.query == title
        assert (NOW - partition.start).days == 30
        snapshot = await journal.snapshot(run.scan_id, now=NOW)
        article = next(a for a in snapshot.articles if a.source.canonical_url == mirror)
        assert article.source.published_at == (
            datetime(2026, 10, 16, tzinfo=UTC) if imprint else None
        )


@pytest.mark.parametrize("exact_match", [True, False])
async def test_unavailable_reliefweb_citation_uses_official_report_and_pdf_queue(
    tmp_path,
    exact_match,
):
    alias = "https://reliefweb.int/report/world/flood-recovery-assessment"
    canonical = "https://reliefweb.int/node/2288123"
    attachment = (
        "https://reliefweb.int/attachments/75efadba-a944-4ad1-b73e-af535f631b60/"
        "assessment.pdf"
    )
    requests = []
    lookups = []
    pdf = report_pdf(
        "Flood recovery assessment", "Floods killed two people in Riverton."
    )

    class CitationIndex:
        source_id = "citation-index"
        queries = ("flood",)
        supports_time_filter = True
        supports_alternates = False

        async def fetch_page(self, partition):
            if not partition.alternate_for:
                return CollectionPage(
                    children=(
                        replace(
                            partition,
                            query="alternate-title",
                            depth=1,
                            alternate_for="https://reports.example/unavailable.pdf",
                        ),
                    )
                )
            return CollectionPage(
                leads=(
                    NewsFeedItem(
                        alias, "Index", "Flood recovery assessment", alias, None, None
                    ),
                )
            )

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        host = request.headers["host"]
        requests.append((host, request.url.path))
        if host == "api.reliefweb.int":
            params = request.url.params
            if params.get("filter[field]") != "url_alias":
                return httpx.Response(200, json={"totalCount": 0, "data": []})
            assert params["filter[value]"] == alias and params["limit"] == "2"
            lookups.append(alias)
            return httpx.Response(
                200,
                json={
                    "totalCount": 1,
                    "data": [
                        {
                            "fields": {
                                "title": "Flood recovery assessment",
                                "url": canonical,
                                "url_alias": alias if exact_match else alias + "-other",
                                "status": "published",
                                "date": {"original": "2026-10-16T08:00:00Z"},
                                "source": [{"name": "Emergency Authority"}],
                                "body": "Floods killed two people in Riverton.",
                                "file": [
                                    {
                                        "url": "https://unrelated.example/other.pdf",
                                        "mimetype": "application/pdf",
                                    },
                                    {
                                        "url": attachment,
                                        "mimetype": "application/pdf",
                                        "filename": "assessment.pdf",
                                    },
                                ],
                            }
                        }
                    ],
                },
            )
        if request.url.path == httpx.URL(alias).path:
            return httpx.Response(403)
        assert request.url.path == httpx.URL(attachment).path
        return httpx.Response(
            200, content=pdf, headers={"content-type": "application/pdf"}
        )

    journal = SQLiteCollectionJournal(tmp_path / "reliefweb.sqlite")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        index = ReliefWebCollectionProvider(
            app_name="approved-test", client=client, minimum_interval=0
        )
        service = ResumableDiscovery(
            (CitationIndex(), index),
            PublicCollectionArticleReader(
                reader=PublicDocumentReader(
                    client=client, resolver=lambda host: ("93.184.216.34",)
                )
            ),
            journal,
            clock=lambda: NOW,
            pass_seconds=3,
        )
        try:
            run = await service.start(3)
            await service.wait(run.scan_id)
        finally:
            await service.aclose()
    snapshot = await journal.snapshot(run.scan_id, now=NOW)
    articles = {item.source.canonical_url: item for item in snapshot.articles}
    assert lookups == [alias]
    assert (("reliefweb.int", httpx.URL(attachment).path) in requests) == exact_match
    assert bool(articles) == exact_match
    if exact_match:
        assert set(articles) == {canonical, attachment}
        assert articles[canonical].source.publisher == "Emergency Authority"
        assert articles[canonical].source.published_at == datetime(
            2026, 10, 16, 8, tzinfo=UTC
        )
        assert articles[attachment].source.published_at is None
