"""Body-derived GKG metadata supplies leads without supplying publisher facts."""

import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.domain.collection import (
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.infrastructure.news.gdelt_gkg import GdeltGkgCollectionProvider

NOW = datetime(2026, 10, 22, 13, tzinfo=UTC)
START = NOW.replace(hour=12, minute=0)


def row(**changes):
    fields = [""] * 27
    values = {
        0: "20261022123000-1",
        1: "20261022123000",
        2: "1",
        3: "regional.example",
        4: "https://regional.example/report",
        7: "NATURAL_DISASTER_LANDSLIDE;KILL;",
        26: "<PAGE_TITLE>Últimas noticias &amp; rescate</PAGE_TITLE>",
    }
    values.update({int(k.removeprefix("c")): v for k, v in changes.items()})
    for index, value in values.items():
        fields[index] = value
    return "\t".join(fields)


def zipped(*rows, name="20261022123000.gkg.csv"):
    return zipped_bytes(("\n".join(rows) + "\n").encode(), name=name)


def zipped_bytes(data, name="20261022123000.gkg.csv"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, data)
    return out.getvalue()


def partition(provider, **changes):
    return replace(
        CollectionPartition(provider.source_id, provider.queries[0], START, NOW),
        **changes,
    )


async def fetch(data, **options):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=data))
    ) as client:
        provider = GdeltGkgCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW, **options
        )
        return await provider.fetch_page(
            partition(provider, end=START + timedelta(minutes=45))
        )


async def test_body_theme_retains_native_title_and_index_only_context():
    page = await fetch(zipped(row()))
    (lead,) = page.leads
    assert lead.title == "Últimas noticias & rescate"
    assert lead.search_title == lead.title
    assert lead.published_at is None and lead.updated_at is None
    assert lead.indexed_at == START + timedelta(minutes=30)
    assert lead.canonical_url == "https://regional.example/report"
    assert lead.publisher == "regional.example"
    assert "landslide" in lead.discovery_hint
    assert "death" in lead.discovery_hint
    assert not page.articles and not page.supplemental
    assert page.saturated and page.next_cursor
    assert any("never" in n and "publication" in n for n in page.notices)


async def test_every_quarterhour_and_both_language_streams_have_durable_positions():
    paths = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: (paths.append(r.url.path), httpx.Response(404))[1]
        )
    ) as client:
        provider = GdeltGkgCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        for query in provider.queries:
            part = partition(provider, query=query)
            while True:
                page = await provider.fetch_page(part)
                assert any("404" in n for n in page.notices)
                assert page.saturated and not page.leads
                assert page.requested_end - page.requested_start == timedelta(
                    minutes=15
                )
                if page.next_cursor is None:
                    break
                part = replace(part, cursor=page.next_cursor)
    assert len(paths) == len(set(paths)) == 8
    assert paths[0].endswith("20261022124500.gkg.csv.zip")
    assert paths[4].endswith("20261022124500.translation.gkg.csv.zip")


@pytest.mark.parametrize(
    "changes",
    [
        {"c2": "2"},
        {"c4": "https://127.0.0.1/private"},
        {"c4": "https://user:pass@regional.example/report"},
        {"c7": "NOT_NATURAL_DISASTER_LANDSLIDE;"},
        {"c7": "KILL;"},
        {"c26": "<PAGE_TITLE></PAGE_TITLE>"},
        {"c1": "20261020123000"},
        {"c0": "other-record"},
    ],
)
async def test_unusable_or_unrelated_metadata_cannot_supply_a_lead(changes):
    assert not (await fetch(zipped(row(**changes)))).leads


async def test_body_hazards_do_not_require_death_or_headline_wording():
    themes = [
        "EARTHQUAKE",
        "FLOOD",
        "FOREST_FIRE",
        "LANDSLIDE",
        "TYPHOON",
        "ERUPTION",
        "DROUGHT",
    ]
    page = await fetch(
        zipped(
            *(
                row(c4=f"https://regional.example/{i}", c7="NATURAL_DISASTER_" + t)
                for i, t in enumerate(themes)
            )
        )
    )
    assert len(page.leads) == 7
    assert all("death" not in lead.discovery_hint for lead in page.leads)


@pytest.mark.parametrize(
    "data",
    [b"not zip", zipped(row(), name="../escape.csv"), zipped("too\tfew\tfields")],
)
async def test_malformed_or_unsafe_archive_is_an_explicit_failure(data):
    with pytest.raises(CollectionProviderError, match="GKG"):
        await fetch(data)


async def test_decoded_archive_is_bounded_before_reading_member():
    with pytest.raises(CollectionProviderError, match="GKG"):
        await fetch(zipped(row(c26="x" * 2000)), maximum_decoded_bytes=1000)


@pytest.mark.parametrize(
    "cursor",
    ["garbage", "20261022123001:1", "20261022123000:99999", "20271022123000:1"],
)
async def test_invalid_continuation_fails_before_network(cursor):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("network"))
    ) as client:
        provider = GdeltGkgCollectionProvider(client=client, clock=lambda: NOW)
        with pytest.raises(CollectionProviderError):
            await provider.fetch_page(partition(provider, cursor=cursor))


async def test_continuation_freezes_upper_boundary_as_clock_advances():
    clock = [NOW]
    paths = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: (paths.append(r.url.path), httpx.Response(404))[1]
        )
    ) as client:
        provider = GdeltGkgCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: clock[0]
        )
        part = partition(provider, end=NOW + timedelta(hours=2))
        first = await provider.fetch_page(part)
        clock[0] += timedelta(hours=1)
        second = await provider.fetch_page(replace(part, cursor=first.next_cursor))
    assert first.requested_start == NOW - timedelta(minutes=15)
    assert second.requested_start == NOW - timedelta(minutes=30)
    assert len(paths) == 2


async def test_repeated_urls_do_not_duplicate_publisher_work():
    page = await fetch(zipped(row(), row(c0="20261022123000-2")))
    assert len(page.leads) == 1


@pytest.mark.parametrize("bad_row", [b"\xffbad encoding", b"too\tfew\tfields"])
async def test_one_malformed_metadata_row_does_not_discard_valid_publisher_leads(
    bad_row,
):
    payload = b"\n".join(
        [
            row().encode(),
            bad_row,
            row(c0="20261022123000-2", c4="https://other.example/report").encode(),
        ]
    )
    page = await fetch(zipped_bytes(payload))
    assert {lead.canonical_url for lead in page.leads} == {
        "https://regional.example/report",
        "https://other.example/report",
    }
    assert any("excluded 1 unusable metadata rows" in notice for notice in page.notices)


async def test_archive_without_any_valid_utf8_schema_row_stays_a_failure():
    with pytest.raises(CollectionProviderError, match="GKG"):
        await fetch(zipped_bytes(b"\xffinvalid\n"))


@pytest.mark.parametrize(
    "status,outcome",
    [(429, "rate_limited"), (403, "access_refused"), (503, "transport_failed")],
)
async def test_provider_failures_preserve_outcomes_and_retry_after(status, outcome):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, headers={"Retry-After": "1200"})
        )
    ) as client:
        provider = GdeltGkgCollectionProvider(client=client, clock=lambda: NOW)
        with pytest.raises(CollectionProviderError) as caught:
            await provider.fetch_page(partition(provider))
    assert caught.value.outcome == outcome
    assert caught.value.retry_after_seconds == 1200


async def test_index_url_size_exceeds_transport_limit_explicitly():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * 16_000_001)
        )
    ) as client:
        provider = GdeltGkgCollectionProvider(client=client, clock=lambda: NOW)
        with pytest.raises(CollectionProviderError, match="byte limit"):
            await provider.fetch_page(partition(provider))
