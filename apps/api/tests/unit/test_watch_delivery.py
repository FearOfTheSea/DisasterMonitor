import json
from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.watches.digest import WatchDigestBuilder
from disaster_monitor.domain.spatial_watches import WatchFinding, WatchGeometryRole
from disaster_monitor.infrastructure.notifications.ntfy import NtfyDelivery
from disaster_monitor.infrastructure.notifications.web_push import (
    BrowserPushDelivery,
    BrowserPushSubscription,
    LocalWebPushStateStore,
    VapidApplicationState,
)

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _finding(identifier: str = "finding:1") -> WatchFinding:
    return WatchFinding(
        finding_id=identifier,
        watch_id="watch:1",
        asset_id="asset:warehouse",
        asset_name="Warehouse",
        asset_version="v2",
        evidence_id="cap:warning-7",
        source_id="meteoalarm-at",
        role=WatchGeometryRole.OFFICIAL_WARNING,
        geometry_version="cap:sent-1",
        geometry_hash="a" * 64,
        distance_km=0,
        created_at=NOW,
        summary="Warehouse intersects an official warning area",
    )


@pytest.mark.asyncio
async def test_browser_push_payload_comes_only_from_finding_fields() -> None:
    delivered: list[tuple[str, bytes, str, str]] = []

    async def sender(endpoint: str, payload: bytes, public_key: str, auth: str) -> None:
        delivered.append((endpoint, payload, public_key, auth))

    adapter = BrowserPushDelivery(sender=sender)
    await adapter.deliver(
        BrowserPushSubscription("https://push.local/sub/1", "key", "auth"),
        _finding(),
    )

    payload = json.loads(delivered[0][1])
    assert payload["title"] == "DisasterMonitor watch finding"
    assert payload["body"] == "Warehouse intersects an official warning area"
    assert payload["finding_id"] == "finding:1"


@pytest.mark.asyncio
async def test_ntfy_rejects_public_service_and_posts_to_explicit_self_host() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "message-1"})

    with pytest.raises(ValueError, match="public ntfy"):
        NtfyDelivery(base_url="https://ntfy.sh", allowed_hosts=frozenset({"ntfy.sh"}))
    adapter = NtfyDelivery(
        base_url="https://ntfy.ops.internal",
        allowed_hosts=frozenset({"ntfy.ops.internal"}),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        await adapter.deliver("incidents", _finding())
    finally:
        await adapter.aclose()
    assert requests[0].url == "https://ntfy.ops.internal/incidents"
    assert requests[0].headers["x-title"] == "DisasterMonitor watch finding"


def test_digest_groups_changes_without_model_generated_text() -> None:
    digest = WatchDigestBuilder().build(
        digest_id="digest:2026-09-14",
        starts_at=datetime(2026, 9, 14, tzinfo=UTC),
        ends_at=datetime(2026, 9, 15, tzinfo=UTC),
        findings=(_finding("finding:1"), _finding("finding:2")),
        warning_changes=("Tsunami warning cancelled by NOAA",),
        evidence_changes=("USGS ShakeMap updated from v3 to v4",),
        source_degradations=("GloFAS unavailable",),
    )

    assert digest.groups[0].kind == "asset_intersections"
    assert digest.groups[0].count == 2
    assert "Tsunami warning cancelled by NOAA" in digest.rendered_text


def test_web_push_state_is_self_hosted_and_owner_only(tmp_path) -> None:
    path = tmp_path / "private" / "web-push.json"
    store = LocalWebPushStateStore(path)
    application = VapidApplicationState(
        subject="mailto:operator@example.test",
        public_key="public-vapid-key",
        private_key="private-vapid-key",
    )
    subscription = BrowserPushSubscription(
        "https://push.local/sub/1", "browser-key", "browser-auth"
    )

    store.initialize(application)
    store.save_subscription("desktop-browser", subscription)

    reopened = LocalWebPushStateStore(path)
    assert reopened.application() == application
    assert reopened.subscriptions() == (("desktop-browser", subscription),)
    assert path.stat().st_mode & 0o777 == 0o600
    assert "private-vapid-key" in path.read_text(encoding="utf-8")
