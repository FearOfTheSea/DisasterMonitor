import httpx
import pytest

from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import get_json


class _TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.reads = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_http_rejects_oversize_before_reading_and_stops_chunked_read() -> None:
    declared = _TrackingStream([b"never read"])
    chunked = _TrackingStream([b"{}", b"more data that must not be read"])

    def handler(request: httpx.Request) -> httpx.Response:
        stream = declared if request.url.path.endswith("declared") else chunked
        headers = {"content-type": "application/json"}
        if stream is declared:
            headers["content-length"] = "100"
        return httpx.Response(200, headers=headers, stream=stream, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DisasterProviderResponseError, match="size limit"):
            await get_json(
                client,
                "https://example.test/declared",
                allowed_hosts=frozenset({"example.test"}),
                max_bytes=10,
            )
        with pytest.raises(DisasterProviderResponseError, match="size limit"):
            await get_json(
                client,
                "https://example.test/chunked",
                allowed_hosts=frozenset({"example.test"}),
                max_bytes=2,
            )
    assert declared.reads == 0
    assert chunked.reads == 2


@pytest.mark.asyncio
async def test_http_recovers_from_one_transient_network_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("transient", request=request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"status":"ok"}',
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await get_json(
            client,
            "https://example.test/feed",
            allowed_hosts=frozenset({"example.test"}),
        )

    assert payload == {"status": "ok"}
    assert attempts == 2
