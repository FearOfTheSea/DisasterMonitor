"""Bounded Atom feed adapter for linked CAP 1.2 warning documents."""

from __future__ import annotations

from datetime import datetime

import httpx
from defusedxml import ElementTree

from disaster_monitor.application.ports.weather_alerts import (
    WeatherAlertBatch,
    WeatherAlertProviderIssue,
)
from disaster_monitor.domain.warnings import CapAlert
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_text,
    validate_network_target,
)
from disaster_monitor.infrastructure.weather.cap_parser import parse_cap_alert

_ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"


class AtomCapWarningAdapter:
    def __init__(
        self,
        *,
        feed_urls: tuple[str, ...],
        source_id: str,
        publisher: str,
        attribution: str,
        limitations: tuple[str, ...],
        profile: str,
        allowed_hosts: frozenset[str],
        rights_id: str,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        maximum_response_bytes: int = 3_000_000,
        maximum_records: int = 500,
    ) -> None:
        if not feed_urls or maximum_records < 1:
            raise ValueError("An Atom CAP adapter requires feeds and a record limit.")
        for url in feed_urls:
            validate_network_target(url, allowed_hosts)
        self._feed_urls = tuple(dict.fromkeys(feed_urls))
        self.source_id = source_id
        self.publisher = publisher
        self.attribution = attribution
        self.limitations = limitations
        self.profile = profile
        self.allowed_hosts = allowed_hosts
        self.rights_id = rights_id
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._maximum_response_bytes = maximum_response_bytes
        self._maximum_records = maximum_records

    async def fetch_active_alerts(self, *, now: datetime) -> WeatherAlertBatch:
        links: list[str] = []
        failures = 0
        invalid_links = 0
        for feed_url in self._feed_urls:
            capture = build_snapshot_capture(
                self._snapshot_recorder,
                source_id=self.source_id,
                parameters={"feed_url": feed_url},
                rights_id=self.rights_id,
                retrieved_at=now,
            )
            try:
                document = await get_text(
                    self._client,
                    feed_url,
                    headers={"Accept": "*/*"},
                    capture=capture,
                    allowed_hosts=self.allowed_hosts,
                    max_bytes=self._maximum_response_bytes,
                    provider_name=self.publisher,
                )
                feed_links, invalid = _cap_links(document, self.allowed_hosts)
                links.extend(feed_links)
                invalid_links += invalid
            except (DisasterProviderError, ValueError, ElementTree.ParseError):
                failures += 1
        unique_links = tuple(dict.fromkeys(links))
        reached_limit = len(unique_links) > self._maximum_records
        alerts: list[CapAlert] = []
        malformed = 0
        for link in unique_links[: self._maximum_records]:
            capture = build_snapshot_capture(
                self._snapshot_recorder,
                source_id=self.source_id,
                parameters={"cap_url": link},
                rights_id=self.rights_id,
                retrieved_at=now,
            )
            try:
                cap_document = await get_text(
                    self._client,
                    link,
                    headers={"Accept": "*/*"},
                    capture=capture,
                    allowed_hosts=self.allowed_hosts,
                    max_bytes=self._maximum_response_bytes,
                    provider_name=self.publisher,
                )
                alerts.append(
                    parse_cap_alert(
                        cap_document.encode("utf-8"),
                        source_id=self.source_id,
                        publisher=self.publisher,
                        canonical_url=link,
                        retrieved_at=now,
                        attribution=self.attribution,
                        limitations=self.limitations,
                        profile=self.profile,
                    )
                )
            except (DisasterProviderError, ValueError, ElementTree.ParseError):
                malformed += 1
        alerts.sort(key=lambda item: (item.sent, item.identifier), reverse=True)
        issue = _issue(
            failures=failures,
            invalid_links=invalid_links,
            malformed=malformed,
            reached_limit=reached_limit,
            retained=len(alerts),
        )
        return WeatherAlertBatch(tuple(alerts), issue)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _cap_links(
    document: str, allowed_hosts: frozenset[str]
) -> tuple[tuple[str, ...], int]:
    root = ElementTree.fromstring(document)
    if root.tag != f"{{{_ATOM_NAMESPACE}}}feed":
        raise ValueError("The warning source did not return an Atom feed.")
    links: list[str] = []
    invalid = 0
    for entry in root.findall(f"{{{_ATOM_NAMESPACE}}}entry"):
        selected = next(
            (
                node.attrib.get("href", "").strip()
                for node in entry.findall(f"{{{_ATOM_NAMESPACE}}}link")
                if node.attrib.get("type", "").casefold()
                in {"application/cap+xml", "application/xml"}
                and "cap"
                in (
                    node.attrib.get("title", "")
                    + node.attrib.get("type", "")
                    + node.attrib.get("href", "")
                ).casefold()
            ),
            "",
        )
        if not selected:
            continue
        try:
            validate_network_target(selected, allowed_hosts)
        except DisasterProviderError:
            invalid += 1
            continue
        links.append(selected)
    return tuple(links), invalid


def _issue(
    *,
    failures: int,
    invalid_links: int,
    malformed: int,
    reached_limit: bool,
    retained: int,
) -> WeatherAlertProviderIssue | None:
    if reached_limit:
        return WeatherAlertProviderIssue(
            "record_limit_reached",
            "The Atom feeds exceeded the configured linked-CAP record limit.",
            partial=True,
        )
    if invalid_links:
        return WeatherAlertProviderIssue(
            "invalid_cap_links",
            f"{invalid_links} linked CAP document(s) were outside the source "
            "allowlist.",
            partial=True,
        )
    if malformed:
        return WeatherAlertProviderIssue(
            "malformed_cap_documents",
            f"{malformed} linked CAP document(s) could not be admitted.",
            partial=True,
        )
    if failures:
        return WeatherAlertProviderIssue(
            "atom_feed_unavailable",
            f"{failures} configured Atom feed(s) could not be retrieved.",
            retryable=True,
            partial=retained > 0,
        )
    return None
