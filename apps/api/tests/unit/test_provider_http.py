import httpx
import pytest

from disaster_monitor.application.ports.provider_failures import ProviderFailureReason
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError
from disaster_monitor.infrastructure.disaster.http import get_json

URL = "https://example.test/feed"
HOSTS = frozenset({"example.test"})


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_json_transport_distinguishes_valid_empty_and_no_content() -> None:
    responses = iter(
        (
            httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"ok": True},
            ),
            httpx.Response(204),
            httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"",
            ),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        response = next(responses)
        response.request = request
        return response

    client = _client(handler)
    assert await get_json(client, URL, allowed_hosts=HOSTS) == {"ok": True}
    assert await get_json(client, URL, allowed_hosts=HOSTS) is None
    with pytest.raises(DisasterProviderError) as caught:
        await get_json(client, URL, allowed_hosts=HOSTS)
    assert caught.value.failure.reason_code is ProviderFailureReason.INVALID_PAYLOAD
    await client.aclose()


@pytest.mark.asyncio
async def test_json_transport_classifies_malformed_and_missing_endpoint() -> None:
    responses = iter(
        (
            httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"{not-json",
            ),
            httpx.Response(404, headers={"content-type": "application/json"}),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        response = next(responses)
        response.request = request
        return response

    client = _client(handler)
    with pytest.raises(DisasterProviderError) as malformed:
        await get_json(client, URL, allowed_hosts=HOSTS)
    assert malformed.value.failure.reason_code is ProviderFailureReason.MALFORMED_JSON
    with pytest.raises(DisasterProviderError) as missing:
        await get_json(client, URL, allowed_hosts=HOSTS)
    assert missing.value.failure.reason_code is ProviderFailureReason.ENDPOINT_MISSING
    assert missing.value.failure.http_status == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_json_transport_retries_rate_limits_but_preserves_attempt_metadata() -> (
    None
):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            headers={"content-type": "application/json"},
            request=request,
        )

    client = _client(handler)
    with pytest.raises(DisasterProviderError) as caught:
        await get_json(client, URL, allowed_hosts=HOSTS)
    assert attempts == 2
    assert caught.value.failure.reason_code is ProviderFailureReason.RATE_LIMITED
    assert caught.value.failure.retryable is True
    assert caught.value.failure.http_status == 429
    await client.aclose()
