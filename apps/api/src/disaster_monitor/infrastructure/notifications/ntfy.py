"""Optional explicitly self-hosted ntfy delivery adapter."""

from urllib.parse import quote, urlparse

import httpx

from disaster_monitor.domain.spatial_watches import WatchFinding


class NtfyDelivery:
    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: frozenset[str],
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
            raise ValueError(
                "Self-hosted ntfy URL must use an explicitly allowed HTTPS host."
            )
        if parsed.hostname == "ntfy.sh":
            raise ValueError(
                "The public ntfy service is not a supported production target."
            )
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def deliver(self, topic: str, finding: WatchFinding) -> None:
        if not topic or "/" in topic:
            raise ValueError("ntfy topic must be one URL-safe path segment.")
        response = await self._client.post(
            f"{self._base_url}/{quote(topic, safe='')}",
            content=finding.summary.encode(),
            headers={
                "X-Title": "DisasterMonitor watch finding",
                "X-Tags": "warning",
                "X-Message-ID": finding.finding_id,
            },
            follow_redirects=False,
        )
        response.raise_for_status()
