from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from disaster_monitor.infrastructure.weather.atom_cap import AtomCapWarningAdapter

NOW = datetime(2026, 9, 14, 5, 5, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures"


def _client(requests: list[httpx.Request]) -> httpx.AsyncClient:
    atom = (FIXTURES / "cap_atom_feed.xml").read_bytes()
    cap = (FIXTURES / "cap_multilingual_update.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/feed.atom":
            return httpx.Response(
                200, content=atom, headers={"content-type": "application/atom+xml"}
            )
        if request.url.path == "/cap/fixture.xml":
            return httpx.Response(
                200, content=cap, headers={"content-type": "application/cap+xml"}
            )
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2)


@pytest.mark.asyncio
async def test_atom_adapter_fetches_only_bounded_allowlisted_cap_links() -> None:
    requests: list[httpx.Request] = []
    adapter = AtomCapWarningAdapter(
        feed_urls=("https://warnings.example/feed.atom",),
        source_id="fixture-warning-source",
        publisher="Fixture Authority",
        attribution="Fixture attribution",
        limitations=("Warning only.",),
        profile="CAP-1.2/Fixture",
        allowed_hosts=frozenset({"warnings.example"}),
        rights_id="fixture-rights",
        client=_client(requests),
        maximum_records=5,
    )
    try:
        batch = await adapter.fetch_active_alerts(now=NOW)
    finally:
        await adapter.aclose()

    assert [request.url.path for request in requests] == [
        "/feed.atom",
        "/cap/fixture.xml",
    ]
    assert [request.headers["accept"] for request in requests] == ["*/*", "*/*"]
    assert batch.issue is None
    assert batch.alerts[0].identifier == "2.49.0.1.250.0.fixture"
    assert batch.alerts[0].profile == "CAP-1.2/Fixture"


@pytest.mark.asyncio
async def test_atom_adapter_reports_partial_invalid_links_without_following_them() -> (
    None
):
    atom = (
        (FIXTURES / "cap_atom_feed.xml")
        .read_text()
        .replace(
            "https://warnings.example/cap/fixture.xml",
            "https://untrusted.example/cap/fixture.xml",
        )
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=atom,
                headers={"content-type": "application/atom+xml"},
            )
        )
    )
    adapter = AtomCapWarningAdapter(
        feed_urls=("https://warnings.example/feed.atom",),
        source_id="fixture-warning-source",
        publisher="Fixture Authority",
        attribution="Fixture attribution",
        limitations=("Warning only.",),
        profile="CAP-1.2/Fixture",
        allowed_hosts=frozenset({"warnings.example"}),
        rights_id="fixture-rights",
        client=client,
    )
    try:
        batch = await adapter.fetch_active_alerts(now=NOW)
    finally:
        await adapter.aclose()

    assert batch.alerts == ()
    assert batch.issue is not None
    assert batch.issue.partial is True
    assert batch.issue.reason_code == "invalid_cap_links"
