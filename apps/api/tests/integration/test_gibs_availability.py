"""Advertised NASA times, missing metadata, and last-success coverage."""

import httpx

from disaster_monitor.infrastructure.satellite_imagery.providers import (
    NasaGibsImageryProvider,
)

XML = b"""<Capabilities xmlns="http://www.opengis.net/wmts/1.0" xmlns:ows="http://www.opengis.net/ows/1.1"><Contents><Layer><ows:Identifier>GOES-East_ABI_GeoColor</ows:Identifier><Dimension><ows:Identifier>Time</ows:Identifier><Default>2026-10-11T02:40:00Z</Default><Value>2026-10-11T00:00:00Z/2026-10-11T02:40:00Z/PT10M</Value></Dimension></Layer></Contents></Capabilities>"""


async def test_advertised_default_is_used_and_missing_layers_are_explicit():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=XML)

    provider = NasaGibsImageryProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    rows = await provider.availability()
    by_id = {item.source_id: item for item in rows}
    assert by_id["nasa-goes-east-geocolor"].default_time == "2026-10-11T02:40:00Z"
    assert by_id["nasa-goes-east-geocolor"].state == "available"
    assert by_id["nasa-modis-aqua-true-color"].state == "empty"
    assert by_id["nasa-modis-aqua-true-color"].default_time is None
    await provider.availability()
    assert len(calls) == 1
    await provider.aclose()


async def test_missing_time_and_malformed_metadata_do_not_invent_today():
    provider = NasaGibsImageryProvider(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"<broken>")
            )
        )
    )
    rows = await provider.availability()
    assert all(item.state == "error" and item.default_time is None for item in rows)
    await provider.aclose()


async def test_metadata_failure_retains_advertised_time_and_original_timestamp():
    from datetime import UTC, datetime, timedelta

    from disaster_monitor.infrastructure.satellite_imagery.availability import (
        GibsAvailability,
    )

    current = [datetime(2026, 10, 11, 3, tzinfo=UTC)]
    calls = []

    def respond(request):
        calls.append(request)
        return (
            httpx.Response(200, content=XML) if len(calls) == 1 else httpx.Response(503)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = GibsAvailability(client, clock=lambda: current[0])
        first = await service.availability()
        current[0] += timedelta(minutes=16)
        retained = await service.availability()
        goes = next(
            row for row in retained if row.source_id == "nasa-goes-east-geocolor"
        )
        assert goes.state == "degraded"
        assert goes.default_time == "2026-10-11T02:40:00Z"
        assert goes.metadata_retrieved_at == first[3].metadata_retrieved_at
        await service.availability()
        assert len(calls) == 2


async def test_existing_layer_without_default_time_stays_empty():
    missing = XML.replace(b"<Default>2026-10-11T02:40:00Z</Default>", b"")
    provider = NasaGibsImageryProvider(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=missing)
            )
        )
    )
    rows = await provider.availability()
    assert all(row.default_time is None and row.state == "empty" for row in rows)
    await provider.aclose()
