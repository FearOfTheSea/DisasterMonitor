"""Bounded public HTTPS article access, with robots and pinned public DNS."""

import asyncio
import inspect
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

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
    ) -> None:
        self._client = client
        self._resolver = resolver or resolve_public_addresses
        self._timeout = timeout_seconds

    async def read(self, url: str) -> PublicDocument:
        async with asyncio.timeout(self._timeout):
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
                robots_text = await self._robots(client, robots_url, address)
                robots = RobotFileParser()
                robots.parse(robots_text.splitlines())
                if (
                    robots.crawl_delay(self.user_agent)
                    or robots.crawl_delay("*")
                    or robots.request_rate(self.user_agent)
                    or robots.request_rate("*")
                ):
                    raise ValueError(
                        "Publisher robots policy requires crawl scheduling."
                    )
                visited: set[str] = set()
                for _ in range(6):
                    if url in visited:
                        raise ValueError("Publisher article redirect loop.")
                    visited.add(url)
                    if not robots.can_fetch(self.user_agent, url):
                        raise ValueError(
                            "Publisher robots policy disallows article retrieval."
                        )
                    try:
                        html = await self._get(client, url, address, robots=False)
                        return PublicDocument(html, url)
                    except _Redirect as redirect:
                        target = redirect.destination
                        if public_document_host(target) != hostname or urlsplit(
                            target
                        ).path in ("", "/"):
                            # Other hosts need their own durable publisher leases
                            # and cooldowns; a homepage is not a moved article.
                            raise ValueError(
                                "Publisher redirect requires separate "
                                "access validation."
                            ) from redirect
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

    async def _robots(self, client: httpx.AsyncClient, url: str, address: str) -> str:
        # RFC 9309 section 2.3.1.2: redirected rules govern the initial authority.
        # Keep the HTTPS/public-DNS boundary at every hop and fail closed on loops.
        visited: set[str] = set()
        for _ in range(6):
            if url in visited:
                raise ValueError("Publisher robots redirect loop.")
            visited.add(url)
            try:
                return await self._get(client, url, address, robots=True)
            except _Redirect as redirect:
                url = redirect.destination
                address = await self._address(url)
        raise ValueError("Publisher robots redirect limit exceeded.")

    async def _get(
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
                response.headers.get("content-type", "").split(";", 1)[0].lower()
            )
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
