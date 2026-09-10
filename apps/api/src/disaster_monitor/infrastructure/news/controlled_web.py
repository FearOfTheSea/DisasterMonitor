"""Fail-closed public-web collection behind approved source policy."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit

import httpx

from disaster_monitor.application.ports.web_collection import WebCollectionStore
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.domain.web_collection import (
    ApprovedWebSource,
    WebFetchAudit,
    WebFetchOutcome,
    WebFetchState,
)
from disaster_monitor.infrastructure.news.web_metadata_parser import parse_web_metadata

AddressResolver = Callable[[str], tuple[str, ...] | Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class FetchedWebDocument:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str | None
    body: bytes
    etag: str | None
    last_modified: str | None


class WebFetchFailure(ValueError):
    def __init__(
        self,
        message: str,
        *,
        outcome: WebFetchOutcome,
        error_code: str,
        status_code: int | None = None,
        bytes_received: int = 0,
    ) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.error_code = error_code
        self.status_code = status_code
        self.bytes_received = bytes_received


class BoundedWebFetcher:
    """Fetch one admitted document without relaxing network boundaries."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: AddressResolver | None = None,
        timeout_seconds: float = 15,
        maximum_redirects: int = 3,
    ) -> None:
        if not 0 <= maximum_redirects <= 5:
            raise ValueError("Maximum redirects must be between zero and five.")
        self._client = client
        self._resolver = resolver or _resolve_addresses
        self._timeout_seconds = timeout_seconds
        self._maximum_redirects = maximum_redirects

    async def fetch(
        self,
        source: ApprovedWebSource,
        state: WebFetchState,
    ) -> FetchedWebDocument:
        headers = {
            "User-Agent": source.user_agent,
            "Accept": (
                "application/rss+xml, application/atom+xml, application/xml, text/xml"
            ),
        }
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout_seconds,
            trust_env=False,
        )
        owns_client = self._client is None
        try:
            return await self._request(source, client, headers)
        finally:
            if owns_client:
                await client.aclose()

    async def _request(
        self,
        source: ApprovedWebSource,
        client: httpx.AsyncClient,
        headers: dict[str, str],
    ) -> FetchedWebDocument:
        requested_url = source.feed_url
        url = requested_url
        for redirect_count in range(self._maximum_redirects + 1):
            if not source.allows_url(url):
                raise WebFetchFailure(
                    "Web fetch target is not an admitted URL.",
                    outcome=WebFetchOutcome.POLICY_REJECTED,
                    error_code="url_not_admitted",
                )
            if redirect_count >= source.request_limit_per_run:
                raise WebFetchFailure(
                    "Web source request budget was exhausted.",
                    outcome=WebFetchOutcome.POLICY_REJECTED,
                    error_code="request_budget_exhausted",
                )
            await self._require_public_destination(url)
            async with client.stream(
                "GET", url, headers=headers, follow_redirects=False
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if location is None or redirect_count == self._maximum_redirects:
                        raise WebFetchFailure(
                            "Web fetch redirect exceeded the admitted boundary.",
                            outcome=WebFetchOutcome.POLICY_REJECTED,
                            error_code="redirect_rejected",
                            status_code=response.status_code,
                        )
                    url = urljoin(url, location)
                    continue
                if response.status_code == 304:
                    return FetchedWebDocument(
                        requested_url,
                        url,
                        304,
                        response.headers.get("content-type"),
                        b"",
                        response.headers.get("etag") or headers.get("If-None-Match"),
                        response.headers.get("last-modified")
                        or headers.get("If-Modified-Since"),
                    )
                if response.status_code == 429:
                    raise WebFetchFailure(
                        "Web source rate limited the collector.",
                        outcome=WebFetchOutcome.RATE_LIMITED,
                        error_code="upstream_rate_limited",
                        status_code=429,
                    )
                if response.status_code >= 400:
                    raise WebFetchFailure(
                        "Web source returned an unsuccessful response.",
                        outcome=WebFetchOutcome.UPSTREAM_ERROR,
                        error_code="upstream_http_error",
                        status_code=response.status_code,
                    )
                declared_length = response.headers.get("content-length")
                if (
                    declared_length is not None
                    and declared_length.isdigit()
                    and int(declared_length) > source.maximum_response_bytes
                ):
                    raise WebFetchFailure(
                        "Web source response exceeded the configured size limit.",
                        outcome=WebFetchOutcome.POLICY_REJECTED,
                        error_code="response_too_large",
                        status_code=response.status_code,
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if content_type.casefold() not in {
                    "application/rss+xml",
                    "application/atom+xml",
                    "application/xml",
                    "text/xml",
                }:
                    raise WebFetchFailure(
                        "Web source returned an unsupported content type.",
                        outcome=WebFetchOutcome.POLICY_REJECTED,
                        error_code="unsupported_content_type",
                        status_code=response.status_code,
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > source.maximum_response_bytes:
                        raise WebFetchFailure(
                            "Web source response exceeded the configured size limit.",
                            outcome=WebFetchOutcome.POLICY_REJECTED,
                            error_code="response_too_large",
                            status_code=response.status_code,
                            bytes_received=len(body),
                        )
                return FetchedWebDocument(
                    requested_url,
                    url,
                    response.status_code,
                    content_type,
                    bytes(body),
                    response.headers.get("etag"),
                    response.headers.get("last-modified"),
                )
        raise AssertionError(
            "Redirect loop must terminate within its configured bound."
        )

    async def _require_public_destination(self, url: str) -> None:
        host = urlsplit(url).hostname
        if host is None:
            raise WebFetchFailure(
                "Web fetch target is not an admitted URL.",
                outcome=WebFetchOutcome.POLICY_REJECTED,
                error_code="invalid_host",
            )
        addresses = self._resolver(host)
        if inspect.isawaitable(addresses):
            addresses = await addresses
        if not addresses or any(
            not ipaddress.ip_address(address).is_global for address in addresses
        ):
            raise WebFetchFailure(
                "Web fetch target must resolve only to a public destination.",
                outcome=WebFetchOutcome.POLICY_REJECTED,
                error_code="non_public_destination",
            )


class ControlledWebNewsFeed:
    """Expose one approved RSS/Atom source through the news ingestion port."""

    failure_threshold = 3
    circuit_duration = timedelta(minutes=30)

    def __init__(
        self,
        source: ApprovedWebSource,
        fetcher: BoundedWebFetcher,
        store: WebCollectionStore,
    ) -> None:
        self.source_id = source.source_id
        self._source = source
        self._fetcher = fetcher
        self._store = store

    async def fetch_since(
        self, *, since: datetime, now: datetime
    ) -> tuple[NewsFeedItem, ...]:
        if since.tzinfo is None or now.tzinfo is None or since > now:
            raise ValueError("Web feed windows require ordered timezone-aware times.")
        state = await self._store.read_web_fetch_state(self.source_id) or WebFetchState(
            self.source_id
        )
        if not self._source.is_admitted(now):
            await self._record_failure(
                now,
                WebFetchFailure(
                    "Web source is not currently admitted.",
                    outcome=WebFetchOutcome.POLICY_REJECTED,
                    error_code="source_not_admitted",
                ),
                state,
            )
            raise ValueError("Web source is not currently admitted.")
        if state.circuit_open_until is not None and now < state.circuit_open_until:
            raise ValueError("Web source circuit is open.")
        if (
            state.last_attempt_at is not None
            and now
            < state.last_attempt_at
            + timedelta(seconds=self._source.crawl_delay_seconds)
        ):
            raise ValueError("Web source crawl delay has not elapsed.")
        try:
            document = await self._fetcher.fetch(self._source, state)
        except WebFetchFailure as error:
            await self._record_failure(now, error, state)
            raise
        if document.status_code == 304:
            await self._record_success(
                now, document, state, WebFetchOutcome.NOT_MODIFIED
            )
            return ()
        try:
            items = parse_web_metadata(
                self._source, document.body, since=since, now=now
            )
        except ValueError as error:
            failure = WebFetchFailure(
                str(error),
                outcome=WebFetchOutcome.PARSER_ERROR,
                error_code="parser_rejected_document",
                status_code=document.status_code,
                bytes_received=len(document.body),
            )
            await self._record_failure(now, failure, state, document.body)
            raise
        await self._record_success(now, document, state, WebFetchOutcome.SUCCESS)
        return items

    async def _record_success(
        self,
        now: datetime,
        document: FetchedWebDocument,
        state: WebFetchState,
        outcome: WebFetchOutcome,
    ) -> None:
        await self._store.save_web_fetch_state(
            WebFetchState(
                source_id=self.source_id,
                etag=document.etag or state.etag,
                last_modified=document.last_modified or state.last_modified,
                last_attempt_at=now,
                last_success_at=now,
            )
        )
        await self._store.append_web_fetch_audit(
            _audit(
                self._source,
                now,
                outcome,
                status_code=document.status_code,
                body=document.body,
            )
        )

    async def _record_failure(
        self,
        now: datetime,
        error: WebFetchFailure,
        state: WebFetchState,
        body: bytes = b"",
    ) -> None:
        failures = state.consecutive_failures + 1
        await self._store.save_web_fetch_state(
            replace(
                state,
                last_attempt_at=now,
                consecutive_failures=failures,
                circuit_open_until=(
                    now + self.circuit_duration
                    if failures >= self.failure_threshold
                    else state.circuit_open_until
                ),
            )
        )
        await self._store.append_web_fetch_audit(
            _audit(
                self._source,
                now,
                error.outcome,
                status_code=error.status_code,
                body=body,
                bytes_received=error.bytes_received,
                error_code=error.error_code,
            )
        )


def _audit(
    source: ApprovedWebSource,
    attempted_at: datetime,
    outcome: WebFetchOutcome,
    *,
    status_code: int | None,
    body: bytes,
    bytes_received: int | None = None,
    error_code: str | None = None,
) -> WebFetchAudit:
    response_sha256 = hashlib.sha256(body).hexdigest() if body else None
    material = "|".join(
        (
            source.source_id,
            attempted_at.isoformat(),
            outcome.value,
            str(status_code),
            response_sha256 or "",
            error_code or "",
        )
    )
    return WebFetchAudit(
        audit_id=f"web-fetch:{hashlib.sha256(material.encode()).hexdigest()[:32]}",
        source_id=source.source_id,
        requested_url=source.feed_url,
        attempted_at=attempted_at,
        outcome=outcome,
        status_code=status_code,
        bytes_received=len(body) if bytes_received is None else bytes_received,
        response_sha256=response_sha256,
        error_code=error_code,
    )


async def _resolve_addresses(host: str) -> tuple[str, ...]:
    records = await asyncio.to_thread(
        socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM
    )
    return tuple(sorted({str(record[4][0]) for record in records}))
