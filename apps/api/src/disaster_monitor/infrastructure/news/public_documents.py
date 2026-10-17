"""Bounded public HTTPS article access, with robots and pinned public DNS."""

import asyncio
import inspect
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

Resolver = Callable[[str], tuple[str, ...] | Awaitable[tuple[str, ...]]]


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

    async def read(self, url: str) -> str:
        async with asyncio.timeout(self._timeout):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or parsed.fragment
            ):
                raise ValueError("Article URL is outside the public HTTPS boundary.")
            addresses = self._resolver(parsed.hostname)
            if inspect.isawaitable(addresses):
                addresses = await addresses
            if not addresses or any(
                not ipaddress.ip_address(a).is_global for a in addresses
            ):
                raise ValueError(
                    "Article destination must resolve only to public addresses."
                )
            client = self._client or httpx.AsyncClient(
                timeout=self._timeout, trust_env=False
            )
            try:
                # Pin DNS for robots and content; keep the original Host and TLS SNI.
                robots_url = f"https://{parsed.netloc}/robots.txt"
                robots_text = await self._get(
                    client, robots_url, addresses[0], robots=True
                )
                robots = RobotFileParser()
                robots.parse(robots_text.splitlines())
                if not robots.can_fetch(self.user_agent, url):
                    raise ValueError(
                        "Publisher robots policy disallows article retrieval."
                    )
                if (
                    robots.crawl_delay(self.user_agent)
                    or robots.crawl_delay("*")
                    or robots.request_rate(self.user_agent)
                    or robots.request_rate("*")
                ):
                    raise ValueError(
                        "Publisher robots policy requires crawl scheduling."
                    )
                return await self._get(client, url, addresses[0], robots=False)
            finally:
                if self._client is None:
                    await client.aclose()

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
                "Accept": "text/plain" if robots else "text/html,application/xhtml+xml",
            },
            extensions={"sni_hostname": original.host},
        ) as response:
            if robots and response.status_code == 404:
                return "User-agent: *\nDisallow:"
            # Redirects are deliberately not followed: they require a new host policy.
            if response.is_redirect:
                raise ValueError(
                    "Publisher redirect requires separate access validation."
                )
            response.raise_for_status()
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
