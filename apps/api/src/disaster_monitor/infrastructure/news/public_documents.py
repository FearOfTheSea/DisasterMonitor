"""Bounded public HTTPS article access, with robots and pinned public DNS."""

import asyncio
import inspect
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from time import time
from urllib.parse import urljoin, urlsplit

import httpx
from protego import Protego

from disaster_monitor.infrastructure.news.public_document_access import (
    PublicAccessDeferred,
    PublicDocumentAccess,
    PublicRedirectResume,
)

Resolver = Callable[[str], tuple[str, ...] | Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class PublicDocument:
    html: str
    url: str


@dataclass
class _Redirect(Exception):
    destination: str


def public_document_host(url: str) -> str | None:
    """Validate document URL syntax; the reader separately pins public DNS."""
    try:
        parsed = urlsplit(url)
        if (
            any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in url)
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            return None
        return parsed.hostname
    except ValueError:
        return None


class PublicDocumentReader:
    user_agent = "DisasterMonitorDiscovery/1.0"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        timeout_seconds: float = 15,
        access: PublicDocumentAccess | None = None,
        clock: Callable[[], float] = time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._resolver = resolver or resolve_public_addresses
        self._timeout = timeout_seconds
        self._access = access
        self._clock = clock
        self._sleep = sleep

    async def read(self, url: str) -> PublicDocument:
        async with asyncio.timeout(self._timeout):
            deadline = self._clock() + self._timeout
            parsed = urlsplit(url)
            hostname = public_document_host(url)
            if hostname is None:
                raise ValueError("Article URL is outside the public HTTPS boundary.")
            address = await self._address(url)
            client = self._client or httpx.AsyncClient(
                timeout=self._timeout, trust_env=False
            )
            try:
                # Pin DNS for robots and content; keep the original Host and TLS SNI.
                robots_url = f"https://{parsed.netloc}/robots.txt"
                robots_text = (
                    await self._access.robots(hostname, now=self._clock())
                    if self._access
                    else None
                )
                if robots_text is None:
                    robots_text = await self._robots(
                        client, robots_url, address, deadline=deadline
                    )
                robots = Protego.parse(robots_text)
                if _crawl_interval(robots, self.user_agent) and self._access is None:
                    raise ValueError(
                        "Publisher robots policy requires crawl scheduling."
                    )
                initial_url = url
                visited: set[str] = set()
                resume = (
                    await self._access.redirect(initial_url, now=self._clock())
                    if self._access
                    else None
                )
                if resume:
                    _require_article_destination(resume.destination, hostname)
                    url, visited = resume.destination, set(resume.visited)
                for _ in range(6 - len(visited)):
                    identity = _url_identity(url)
                    if identity in visited:
                        raise ValueError("Publisher article redirect loop.")
                    visited.add(identity)
                    if not robots.can_fetch(url, self.user_agent):
                        raise ValueError(
                            "Publisher robots policy disallows article retrieval."
                        )
                    try:
                        html = await self._get(
                            client, url, address, robots=False, deadline=deadline
                        )
                        if self._access:
                            await self._access.clear_redirect(initial_url)
                        return PublicDocument(html, url)
                    except _Redirect as redirect:
                        target = redirect.destination
                        _require_article_destination(target, hostname)
                        if _url_identity(target) in visited:
                            raise ValueError(
                                "Publisher article redirect loop."
                            ) from redirect
                        if self._access and len(visited) <= 5:
                            await self._access.remember_redirect(
                                initial_url,
                                PublicRedirectResume(target, tuple(visited)),
                                now=self._clock(),
                            )
                        url = target
                raise ValueError("Publisher article redirect limit exceeded.")
            finally:
                if self._client is None:
                    await client.aclose()

    async def _address(self, url: str) -> str:
        hostname = public_document_host(url)
        if hostname is None:
            raise ValueError("Document URL is outside the public HTTPS boundary.")
        addresses = self._resolver(hostname)
        if inspect.isawaitable(addresses):
            addresses = await addresses
        if not addresses or any(
            not ipaddress.ip_address(a).is_global for a in addresses
        ):
            raise ValueError(
                "Document destination must resolve only to public addresses."
            )
        return addresses[0]

    async def _robots(
        self,
        client: httpx.AsyncClient,
        url: str,
        address: str,
        *,
        deadline: float | None = None,
    ) -> str:
        # RFC 9309 section 2.3.1.2: redirected rules govern the initial authority.
        # Keep the HTTPS/public-DNS boundary at every hop and fail closed on loops.
        visited: set[str] = set()
        initial_url = url
        policy_host = urlsplit(url).hostname
        resume = (
            await self._access.redirect(initial_url, now=self._clock())
            if self._access
            else None
        )
        if resume:
            url, visited = resume.destination, set(resume.visited)
            address = await self._address(url)
        for _ in range(6 - len(visited)):
            identity = _url_identity(url)
            if identity in visited:
                raise ValueError("Publisher robots redirect loop.")
            visited.add(identity)
            try:
                text = await self._get(
                    client,
                    url,
                    address,
                    robots=True,
                    policy_host=policy_host,
                    deadline=deadline,
                )
                if self._access:
                    await self._access.clear_redirect(initial_url)
                return text
            except _Redirect as redirect:
                url = redirect.destination
                address = await self._address(url)
                if _url_identity(url) in visited:
                    raise ValueError("Publisher robots redirect loop.") from redirect
                if self._access and len(visited) <= 5:
                    await self._access.remember_redirect(
                        initial_url,
                        PublicRedirectResume(url, tuple(visited)),
                        now=self._clock(),
                    )
        raise ValueError("Publisher robots redirect limit exceeded.")

    async def _get(
        self,
        client: httpx.AsyncClient,
        url: str,
        address: str,
        *,
        robots: bool,
        policy_host: str | None = None,
        deadline: float | None = None,
    ) -> str:
        host = urlsplit(url).hostname
        assert host is not None
        token = await self._request_slot(host, deadline) if self._access else None
        try:
            text = await self._download(client, url, address, robots=robots)
            if robots and self._access:
                policy = Protego.parse(text)
                await self._access.remember_robots(
                    policy_host or host,
                    text,
                    _crawl_interval(policy, self.user_agent),
                    now=self._clock(),
                )
            return text
        finally:
            if token and self._access:
                await asyncio.shield(
                    self._access.finish(host, token, now=self._clock())
                )

    async def _request_slot(self, host: str, deadline: float | None) -> str:
        assert self._access is not None
        deadline = deadline if deadline is not None else self._clock() + self._timeout
        while True:
            reservation = await self._access.claim(
                host,
                now=self._clock(),
                lease_seconds=self._timeout + 5,
            )
            if reservation.token:
                return reservation.token
            delay = reservation.retry_after_seconds
            if delay > min(5, max(0, deadline - self._clock() - 1)):
                raise PublicAccessDeferred(delay)
            await self._sleep(delay)

    async def _download(
        self, client: httpx.AsyncClient, url: str, address: str, *, robots: bool
    ) -> str:
        original = httpx.URL(url)
        target = original.copy_with(host=address)
        limit = 100_000 if robots else 1_000_000
        async with client.stream(
            "GET",
            target,
            follow_redirects=False,
            timeout=self._timeout,
            headers={
                "Host": original.host,
                "User-Agent": self.user_agent,
                "Cookie": "",
                "Accept": "text/plain" if robots else "text/html,application/xhtml+xml",
            },
            extensions={"sni_hostname": original.host},
        ) as response:
            if robots and response.status_code == 404:
                return "User-agent: *\nDisallow:"
            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("Publisher redirect has no destination.")
                raise _Redirect(urljoin(url, location))
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError(
                    "Publisher returned a challenge or incomplete document."
                )
            media_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if robots and media_type in {"text/html", "application/xhtml+xml"}:
                raise ValueError("Publisher robots response is an HTML page.")
            if not robots and media_type not in {"text/html", "application/xhtml+xml"}:
                raise ValueError("Article response is not HTML.")
            if int(response.headers.get("content-length", "0")) > limit:
                raise ValueError("Article response exceeds byte limit.")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise ValueError("Article response exceeds byte limit.")
            return bytes(body).decode("utf-8", errors="replace")


async def resolve_public_addresses(host: str) -> tuple[str, ...]:
    records = await asyncio.to_thread(
        socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM
    )
    return tuple(sorted({str(record[4][0]) for record in records}))


def _crawl_interval(robots: Protego, user_agent: str) -> float:
    delay = robots.crawl_delay(user_agent) or robots.crawl_delay("*") or 0
    rate = robots.request_rate(user_agent) or robots.request_rate("*")
    if (
        robots.visit_time(user_agent)
        or robots.visit_time("*")
        or (rate and (rate.start_time is not None or rate.end_time is not None))
    ):
        raise ValueError("Publisher robots access hours require separate scheduling.")
    if rate and (rate.requests <= 0 or rate.seconds <= 0):
        raise ValueError("Publisher robots request rate is invalid.")
    try:
        interval = max(float(delay), rate.seconds / rate.requests if rate else 0)
    except OverflowError as error:
        raise ValueError(
            "Publisher robots interval exceeds supported bounds."
        ) from error
    if not isfinite(interval) or not 0 <= interval <= 31_536_000:
        raise ValueError("Publisher robots interval exceeds supported bounds.")
    return interval


def _url_identity(url: str) -> str:
    return sha256(url.encode()).hexdigest()


def _require_article_destination(url: str, hostname: str) -> None:
    if public_document_host(url) != hostname or urlsplit(url).path in ("", "/"):
        # Other hosts need their own durable publisher leases and cooldowns;
        # a homepage is not a moved article.
        raise ValueError("Publisher redirect requires separate access validation.")
