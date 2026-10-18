"""Bounded request cooldowns and host-wide advertised Retry-After delays."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic
from weakref import WeakKeyDictionary

import httpx

from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    ProviderFailure,
)

_COOLDOWNS: WeakKeyDictionary[
    httpx.AsyncClient, dict[str, tuple[float, ProviderFailure]]
] = WeakKeyDictionary()


def check_cooldown(client: httpx.AsyncClient, url: str) -> None:
    for key in ("host:" + httpx.URL(url).host, _request_key(url)):
        blocked = _COOLDOWNS.get(client, {}).get(key)
        if blocked and blocked[0] > monotonic():
            raise DisasterProviderError(
                "The provider is in backoff after a failed request. Retry later.",
                failure=blocked[1],
            )


def record_failure(
    client: httpx.AsyncClient,
    response: httpx.Response,
    failure: ProviderFailure,
    *,
    final_attempt: bool,
) -> bool:
    header = response.headers.get("Retry-After")
    delay = None
    if header:
        try:
            delay = float(header)
        except ValueError:
            try:
                delay = (
                    parsedate_to_datetime(header) - datetime.now(UTC)
                ).total_seconds()
            except (ValueError, TypeError, OverflowError):
                pass
    defer = delay is not None and delay > 0
    if failure.retryable and (final_attempt or defer):
        _set_cooldown(
            client,
            "host:" + response.url.host
            if defer or response.status_code == 429
            else _request_key(str(response.url)),
            failure,
            max(1, delay if defer and delay is not None else 30),
        )
    return defer


def record_transport_failure(
    client: httpx.AsyncClient, url: str, failure: ProviderFailure
) -> None:
    _set_cooldown(client, _request_key(url), failure, 30)


def _request_key(url: str) -> str:
    parsed = httpx.URL(url)
    return "url:" + str(parsed.copy_with(fragment=""))


def _set_cooldown(
    client: httpx.AsyncClient, host: str, failure: ProviderFailure, delay: float
) -> None:
    hosts = _COOLDOWNS.setdefault(client, {})
    if len(hosts) >= 128 and host not in hosts:
        hosts.pop(next(iter(hosts)))
    hosts[host] = (monotonic() + delay, failure)
