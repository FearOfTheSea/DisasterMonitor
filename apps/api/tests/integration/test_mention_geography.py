from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.incidents.mention_geography import (
    resolve_event_places,
)
from disaster_monitor.application.ports.mention_geography import PlaceResolution
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.geography.nominatim_mentions import (
    NominatimMentionResolver,
)

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
POLYGON = {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]]}


@pytest.mark.parametrize(
    "items,status",
    [
        ([], "unresolved"),
        ([{"addresstype": "country"}], "unresolved"),
        ([{}, {}], "unresolved"),
        (
            [
                {
                    "addresstype": "city",
                    "display_name": "Unrelated city, Country",
                    "geojson": POLYGON,
                    "osm_type": "relation",
                    "osm_id": 123,
                }
            ],
            "unresolved",
        ),
        (
            [
                {
                    "addresstype": "city",
                    "geojson": {"type": "Point", "coordinates": [1, 1]},
                }
            ],
            "unresolved",
        ),
        (
            [
                {
                    "addresstype": "city",
                    "geojson": POLYGON,
                    "osm_type": "relation",
                    "osm_id": 123,
                    "display_name": "Riverton, Country",
                }
            ],
            "resolved",
        ),
    ],
)
async def test_place_resolution_requires_unique_valid_noncountry_polygon_and_caches(
    tmp_path, items, status
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=items)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = NominatimMentionResolver(
            "https://places.example/search", tmp_path / "cache.json", client=client
        )
        first = await adapter.resolve("Riverton", "Country")
        assert first.status == status
        assert await adapter.resolve("Riverton", "Country") == first
        assert len(calls) == 1
        if first.geometry:
            assert first.geometry.estimated
            assert "not a damage footprint" in first.geometry.description
            assert (
                first.geometry.source.canonical_url
                == "https://www.openstreetmap.org/relation/123"
            )
        await adapter.aclose()


async def test_place_failures_and_enrichment_budget_preserve_candidates():
    source = SourceReference(
        "news", "Daily", "Regional update", "https://news.example/one", NOW, None, NOW
    )
    reports = tuple(
        assess_article(
            DiscoveryArticle(
                replace(source, canonical_url=f"https://news.example/{i}"),
                f"Floods hit {place} on 9 October 2026.",
            ),
            ReportingInterval.at_start(7, NOW),
        )
        for i, place in enumerate(["Riverton", "Lakeview", "Hilltown"])
    )

    class Resolver:
        calls = 0

        async def resolve(self, place, country_context):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError()
            return PlaceResolution("ambiguous", detail="Ambiguous place; no selection.")

    resolver = Resolver()
    result = await resolve_event_places(group_reports(reports), resolver, maximum=2)
    assert len(result) == 3
    assert resolver.calls == 2
    assert all(e.geometry is None for e in result)
    assert "failed" in result[0].collection_notices[0]
    assert "budget" in result[2].collection_notices[0]


@pytest.mark.parametrize("point_first", [True, False])
async def test_one_named_boundary_is_usable_when_a_city_centroid_is_also_returned(
    tmp_path, point_first
):
    boundary = {
        "name": "Riverton",
        "addresstype": "province",
        "osm_type": "relation",
        "osm_id": 123,
        "geojson": POLYGON,
    }
    point = {
        "name": "Riverton",
        "addresstype": "city",
        "osm_type": "node",
        "osm_id": 456,
        "geojson": {"type": "Point", "coordinates": [1, 1]},
    }
    items = [point, boundary] if point_first else [boundary, point]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=items))
    ) as client:
        resolver = NominatimMentionResolver(
            "https://places.example/search", tmp_path / "cache.json", client=client
        )
        result = await resolver.resolve("Riverton", "Country")
        assert result.status == "resolved"
        assert result.geometry.estimated
        assert result.geometry.source.canonical_url.endswith("/relation/123")
        assert "not a damage footprint" in result.geometry.description
        await resolver.aclose()


async def test_multiple_matching_boundaries_remain_ambiguous(tmp_path):
    items = [
        {
            "name": "Riverton",
            "addresstype": "province",
            "osm_type": "relation",
            "osm_id": identifier,
            "geojson": POLYGON,
        }
        for identifier in (123, 456)
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=items))
    ) as client:
        resolver = NominatimMentionResolver(
            "https://places.example/search", tmp_path / "cache.json", client=client
        )
        result = await resolver.resolve("Riverton", "Country")
        assert result.status == "ambiguous"
        assert result.geometry is None
        await resolver.aclose()


async def test_bounded_lookup_prioritizes_dated_occurrences_over_forecasts():
    source = SourceReference(
        "news", "Daily", "Regional update", "https://news.example/one", NOW, None, NOW
    )
    reports = tuple(
        assess_article(
            DiscoveryArticle(
                replace(source, canonical_url=f"https://news.example/{i}"), text
            ),
            ReportingInterval.at_start(7, NOW),
        )
        for i, text in enumerate(
            (
                "Forecast floods could hit Lakeview.",
                "An earthquake struck Riverton on 9 October 2026.",
            )
        )
    )
    calls = []

    class Resolver:
        async def resolve(self, place, country_context):
            calls.append(place)
            return PlaceResolution("unresolved", detail="No unique match")

    await resolve_event_places(group_reports(reports), Resolver(), maximum=1)
    assert calls == ["Riverton"]


async def test_compound_named_places_can_supply_explicit_partial_inspection_context():
    source = SourceReference(
        "news",
        "Daily",
        "Earthquake in Highland & River Province",
        "https://news.example/quake",
        NOW,
        None,
        NOW,
    )
    (event,) = group_reports(
        (
            assess_article(
                DiscoveryArticle(
                    source,
                    "An earthquake struck on 9 October 2026.",
                    location="Country",
                ),
                ReportingInterval.at_start(7, NOW),
            ),
        )
    )
    calls = []

    class Resolver:
        async def resolve(self, place, country_context):
            calls.append(place)
            if place == "Highland":
                return PlaceResolution("unresolved", detail="No polygon")
            from disaster_monitor.domain.events import (
                EventCoordinate,
                EventGeometry,
                EventGeometryKind,
            )

            return PlaceResolution(
                "resolved",
                EventGeometry(
                    EventGeometryKind.AREA,
                    source,
                    tuple(
                        EventCoordinate(lat, lon)
                        for lat, lon in ((1, 1), (1, 2), (2, 2), (1, 1))
                    ),
                    description="Administrative context; not a damage footprint",
                    estimated=True,
                ),
                "Administrative context",
            )

    (enriched,) = await resolve_event_places((event,), Resolver(), maximum=2)
    assert calls == ["Highland", "River Province"]
    assert enriched.geometry is not None
    assert "Only River Province" in enriched.geometry.description
    assert "Highland & River Province" in enriched.geometry.description
    assert enriched.location == event.location
