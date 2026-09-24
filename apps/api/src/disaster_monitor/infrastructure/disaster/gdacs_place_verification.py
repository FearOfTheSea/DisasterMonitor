"""Bounded GDACS event-page checks for a user-named flood location."""

import re
import unicodedata
from dataclasses import replace
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlencode

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.domain.disaster import DisasterEvent
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_text,
)

_REPORT_URL = "https://www.gdacs.org/report.aspx"
_MAX_LOOKUPS = 3
_MAX_EPISODES_PER_EVENT = 3


class _Headlines(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headlines: list[str] = []
        self._parts: list[str] | None = None
        self._description_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div":
            if self._description_depth:
                self._description_depth += 1
            elif attributes.get("id") == "item_description":
                self._description_depth = 1
        classes = attributes.get("class") or ""
        if (
            self._description_depth
            and tag == "span"
            and "news_title" in classes.split()
        ):
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._parts is not None:
            headline = " ".join(" ".join(self._parts).split())
            if headline:
                self.headlines.append(headline)
            self._parts = None
        if tag == "div" and self._description_depth:
            self._description_depth -= 1


def _fold(value: str) -> str:
    unaccented = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^\w]+", " ", unaccented).split())


def _contains_place(location: str, place: str) -> bool:
    wanted = _fold(place)
    return bool(
        wanted and re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", _fold(location))
    )


def _region_hint(place: str, country: str) -> str:
    folded = _fold(place)
    country_suffix = f" {_fold(country)}"
    return (
        folded[: -len(country_suffix)].strip()
        if folded.endswith(country_suffix)
        else folded
    )


def _matching_headline(
    html: str, *, place: str, country: str
) -> tuple[str, str] | None:
    parser = _Headlines()
    parser.feed(html)
    country_name = _fold(country)
    for headline in parser.headlines:
        folded = _fold(headline)
        region = headline.split(",", 1)[0].strip()
        if (
            _contains_place(region, _region_hint(place, country))
            and country_name in folded
            and region
        ):
            return headline, region
    return None


def _episode_ids(event: DisasterEvent) -> tuple[int | None, ...]:
    prefix = f"{event.event_id}:"
    numbers = [
        int(identifier.removeprefix(prefix))
        for identifier in event.provider_ids
        if identifier.startswith(prefix) and identifier.removeprefix(prefix).isdigit()
    ]
    if not numbers:
        return (None,)
    latest = max(numbers)
    return tuple(range(latest, max(0, latest - _MAX_EPISODES_PER_EVENT), -1))


async def verify_gdacs_flood_places(
    batch: ProviderBatch[DisasterEvent],
    query: DisasterQuery,
    *,
    now: datetime,
    client: httpx.AsyncClient,
    allowed_hosts: frozenset[str],
    max_response_bytes: int,
    snapshot_recorder: SourcePayloadRecorder | None,
    provider_name: str,
    source_id: str,
) -> ProviderBatch[DisasterEvent]:
    """Enrich only source-correlated events with an exact report headline place."""
    if not query.location_hint:
        return batch
    events = list(batch.records)
    issues = list(batch.issues)
    checked = 0
    for index, event in enumerate(events):
        if _contains_place(
            event.location,
            _region_hint(query.location_hint, query.country.canonical_name),
        ):
            continue
        if checked >= _MAX_LOOKUPS:
            issues.append(
                ProviderIssue(
                    provider_name,
                    "GDACS: The regional report lookup limit was reached; other "
                    "country events may mention the requested place.",
                    reason_code="place_detail_limit_reached",
                )
            )
            break
        checked += 1
        identifier = event.event_id.rsplit(":", 1)[-1]
        for episode_id in _episode_ids(event):
            params: dict[str, str] = {"eventid": identifier, "eventtype": "FL"}
            if episode_id is not None:
                params["episodeid"] = str(episode_id)
            report_url = f"{_REPORT_URL}?{urlencode(params)}"
            capture = build_snapshot_capture(
                snapshot_recorder,
                source_id=source_id,
                parameters=params,
                rights_id="gdacs-terms-of-use",
                retrieved_at=now,
            )
            try:
                page = await get_text(
                    client,
                    _REPORT_URL,
                    params=params,
                    allowed_hosts=allowed_hosts,
                    max_bytes=min(max_response_bytes, 200_000),
                    provider_name=provider_name,
                    capture=capture,
                )
            except DisasterProviderError as error:
                issues.append(
                    ProviderIssue(
                        provider_name,
                        "GDACS: A regional event report could not be checked.",
                        reason_code=error.failure.reason_code,
                    )
                )
                continue
            match = _matching_headline(
                page,
                place=query.location_hint,
                country=query.country.canonical_name,
            )
            if match is None:
                continue
            headline, region = match
            source = replace(
                event.source,
                title=headline,
                canonical_url=report_url,
                published_at=None,
                updated_at=None,
                retrieved_at=now,
                snapshot_id=(
                    capture.snapshot.snapshot_id
                    if capture is not None and capture.snapshot is not None
                    else None
                ),
            )
            events[index] = replace(
                event,
                location=f"{region}, {query.country.canonical_name}",
                location_source=source,
            )
            break
    return ProviderBatch(
        records=tuple(events),
        issues=tuple(issues),
        scan_complete=batch.scan_complete,
        records_seen=batch.records_seen,
    )
