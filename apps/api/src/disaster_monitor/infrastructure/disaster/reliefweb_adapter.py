"""Supplementary ReliefWeb situation-report adapter."""

import html
import re
from datetime import UTC, datetime, timedelta

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
    sanitize_provider_text,
)
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    EventMeasurement,
    FactStatus,
    Hazard,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    HttpParam,
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_json,
    validate_network_target,
)

RELIEFWEB_REPORTS_URL = "https://api.reliefweb.int/v2/reports"
_NUMBER = (
    r"(?:about\s+|approximately\s+)?"
    r"(?P<number>[0-9][0-9,]*|one|two|three|four|five|six|seven|eight|nine|ten)"
)
_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}
_RELIEFWEB_HAZARDS = {
    Hazard.EARTHQUAKE: "Earthquake",
    Hazard.TSUNAMI: "Tsunami",
    Hazard.FLOOD: "Flood",
    Hazard.WILDFIRE: "Wild Fire",
    Hazard.LANDSLIDE: "Land Slide",
    Hazard.TROPICAL_CYCLONE: "Tropical Cyclone",
}


def _reliefweb_datetime(value: datetime) -> str:
    """Return a URL-safe ISO-8601 timestamp for ReliefWeb date filters."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


def build_reliefweb_params(
    event: DisasterEvent,
    query: DisasterQuery,
    *,
    now: datetime,
    app_name: str,
) -> dict[str, HttpParam]:
    """Build bounded ReliefWeb scope filters for one normalized query.

    Event location is deliberately not sent as a free-text query. ReliefWeb's
    query parser treats whitespace-separated terms as required when the
    operator is ``AND``; requiring every selected-provider location token
    makes otherwise relevant country/hazard reports disappear. Event-specific
    correlation remains application-owned after retrieval.
    """
    fields = (
        "id",
        "title",
        "body",
        "url",
        "date",
        "disaster",
        "country",
        "primary_country",
        "disaster_type",
        "format",
        "source",
    )
    start = query.date_from or now - timedelta(days=query.time_window_days)
    end = query.date_to or now + timedelta(minutes=5)
    params: dict[str, HttpParam] = {
        "appname": app_name,
        "filter[operator]": "AND",
        "filter[conditions][0][field]": "country.name",
        "filter[conditions][0][value]": query.country.canonical_name,
        "filter[conditions][1][field]": "disaster_type.name",
        "filter[conditions][1][value]": _RELIEFWEB_HAZARDS[query.hazard],
        "filter[conditions][2][field]": "date.created",
        "filter[conditions][2][value][from]": _reliefweb_datetime(start),
        "filter[conditions][2][value][to]": _reliefweb_datetime(end),
        "limit": 20,
        "sort[]": "date.created:desc",
    }
    for index, field in enumerate(fields):
        params[f"fields[include][{index}]"] = field
    return params


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _nested_text(value: object) -> str:
    if isinstance(value, dict):
        return _text(value.get("name")) or _text(value.get("title"))
    if isinstance(value, list):
        for item in value:
            result = _nested_text(item)
            if result:
                return result
    return ""


def _metadata(
    fields: dict[str, object],
    narrative: str = "",
) -> tuple[
    datetime | None,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    float | None,
]:
    """Extract only bounded event metadata from the ReliefWeb shape."""
    event_time: datetime | None = None
    event_ids: list[str] = []
    locations: list[str] = []
    countries: list[str] = []
    magnitude: float | None = None
    disasters = fields.get("disaster")
    items = disasters if isinstance(disasters, list) else [disasters]
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = _text(item.get("id"))
        if identifier:
            event_ids.append(f"reliefweb:{identifier}")
        date_value = item.get("date")
        if isinstance(date_value, dict):
            date_value = date_value.get("occurred") or date_value.get("start")
        parsed = normalize_timestamp(date_value)
        if parsed is not None:
            event_time = event_time or parsed
    for key in ("location", "primary_location", "affected_location"):
        value = fields.get(key)
        if isinstance(value, list):
            locations.extend(
                item for item in (_nested_text(entry) for entry in value) if item
            )
        else:
            value_text = _nested_text(value)
            if value_text:
                locations.append(value_text)
    for key in ("country", "primary_country", "affected_country"):
        value = fields.get(key)
        if isinstance(value, list):
            countries.extend(
                item for item in (_nested_text(entry) for entry in value) if item
            )
        else:
            value_text = _nested_text(value)
            if value_text:
                countries.append(value_text)
    magnitude_values: list[float] = []
    for expression in (
        r"(?:\bm\s*|magnitude\s*(?:of\s*)?|earthquake\s+measuring\s+)"
        r"(?P<magnitude>[0-9]+(?:\.[0-9]+)?)\b",
        r"\b(?P<magnitude>[0-9]+(?:\.[0-9]+)?)\s+earthquake\b",
        r"\b(?P<magnitude>[0-9]+(?:\.[0-9]+)?)\s+magnitude\s+earthquake\b",
    ):
        magnitude_values.extend(
            float(match.group("magnitude"))
            for match in re.finditer(expression, narrative, re.IGNORECASE)
        )
    if magnitude_values:
        magnitude = max(magnitude_values)
    return (
        event_time,
        tuple(dict.fromkeys(locations)),
        tuple(dict.fromkeys(countries)),
        tuple(dict.fromkeys(event_ids)),
        magnitude,
    )


def _find_number(text: str, expressions: tuple[str, ...]) -> str | None:
    for expression in expressions:
        match = re.search(expression, text, re.IGNORECASE)
        if match:
            value = match.group("number")
            return _NUMBER_WORDS.get(value.lower(), value.replace(",", ""))
    return None


def _make_fact(
    category: str,
    label: str,
    value: str | None,
    source: SourceReference,
    event: DisasterEvent,
    observed_at: datetime | None,
) -> ReportedFact | None:
    if value is None:
        return None
    return ReportedFact(
        category=category,
        label=label,
        value=value,
        status=FactStatus.PRELIMINARY,
        source=source,
        event_id=event.event_id,
        observed_at=observed_at,
        claim_id=category,
    )


class ReliefWebSituationAdapter:
    """Retrieve supplementary reports without treating them as official totals."""

    provider_name = "ReliefWeb"
    source_id = "reliefweb-situation-reports"
    allowed_hosts = frozenset(
        {"api.reliefweb.int", "reliefweb.int", "www.reliefweb.int"}
    )

    def __init__(
        self,
        *,
        app_name: str | None = None,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._app_name = app_name
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    @property
    def configured(self) -> bool:
        """Return whether an explicitly supplied, non-placeholder app name exists."""
        return bool(
            self._app_name
            and self._app_name.strip()
            and self._app_name.strip().lower()
            not in {
                "disaster-monitor-local",
                "change-me",
                "your-app-name",
            }
        )

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        if not self.configured:
            return ProviderBatch(records=())
        assert self._app_name is not None
        params = build_reliefweb_params(event, query, now=now, app_name=self._app_name)
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "country": query.country.alpha3_code,
                "hazard": query.hazard.value,
                "event": event.event_id,
            },
            rights_id="reliefweb-api-partner-rights-2026-08",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            RELIEFWEB_REPORTS_URL,
            allowed_hosts=self.allowed_hosts,
            params=params,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise DisasterProviderResponseError(
                "The ReliefWeb response had no report list."
            )
        reports: list[SituationReport] = []
        malformed = False
        minimum_date = now - timedelta(days=query.time_window_days)
        for item in payload["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("fields"), dict):
                malformed = True
                continue
            fields = item["fields"]
            title = _text(fields.get("title"))
            url = _text(fields.get("url"))
            if not title or not url or not url.startswith("https://"):
                malformed = True
                continue
            try:
                validate_network_target(url, self.allowed_hosts)
            except DisasterProviderResponseError:
                malformed = True
                continue
            published_at = normalize_timestamp(
                fields.get("date", {}).get("created")
                if isinstance(fields.get("date"), dict)
                else None
            )
            if published_at is not None and published_at < minimum_date:
                continue
            updated_at = normalize_timestamp(
                fields.get("date", {}).get("changed")
                if isinstance(fields.get("date"), dict)
                else None
            )
            source = SourceReference(
                source_id=self.source_id,
                publisher="ReliefWeb",
                title=title,
                canonical_url=url,
                published_at=published_at,
                updated_at=updated_at,
                retrieved_at=now,
                authority=SourceAuthority.HUMANITARIAN_AGGREGATOR,
                snapshot_id=capture.snapshot.snapshot_id
                if capture and capture.snapshot
                else None,
            )
            raw_body = fields.get("body") or ""
            if not raw_body:
                malformed = True
            narrative = sanitize_provider_text(html.unescape(_text(raw_body)))
            facts = self._extract_facts(narrative, source, event, published_at)
            (
                reported_event_time,
                locations,
                countries,
                provider_event_ids,
                magnitude,
            ) = _metadata(fields, narrative)
            report = SituationReport(
                source=source,
                narrative=narrative,
                facts=tuple(facts),
                reported_event_time=reported_event_time,
                locations=locations,
                countries=countries,
                hazard=query.hazard,
                measurements=(
                    (EventMeasurement("magnitude", magnitude),)
                    if magnitude is not None
                    else ()
                ),
                provider_event_ids=provider_event_ids,
            )
            reports.append(report)
        issues: tuple[ProviderIssue, ...] = ()
        if malformed and not reports:
            issues = (
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: Required report fields were missing.",
                    reason_code="invalid_payload",
                ),
            )
        elif not reports:
            issues = (
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: The provider returned no matching records.",
                    reason_code="empty_result",
                ),
            )
        return ProviderBatch(records=tuple(reports), issues=issues)

    @staticmethod
    def _extract_facts(
        narrative: str,
        source: SourceReference,
        event: DisasterEvent,
        observed_at: datetime | None,
    ) -> list[ReportedFact]:
        facts: list[ReportedFact] = []
        patterns: tuple[tuple[str, str, tuple[str, ...]], ...] = (
            (
                "fatalities",
                "Fatalities",
                (
                    rf"{_NUMBER}\s+(?:people\s+)?(?:were\s+)?"
                    r"(?:killed|dead|reported dead|fatalities)",
                ),
            ),
            (
                "injuries",
                "Injuries",
                (rf"{_NUMBER}\s+(?:people\s+)?(?:were\s+)?injured",),
            ),
            (
                "missing",
                "Missing people",
                (rf"{_NUMBER}\s+(?:people\s+)?(?:are\s+)?missing",),
            ),
            (
                "evacuations",
                "Evacuations",
                (rf"{_NUMBER}\s+(?:people\s+)?(?:were\s+)?evacuated",),
            ),
            (
                "buildings",
                "Buildings damaged or destroyed",
                (
                    rf"{_NUMBER}\s+(?:buildings|homes|houses)\s+(?:were\s+)?(?:damaged|destroyed)",
                ),
            ),
        )
        for category, label, expressions in patterns:
            fact = _make_fact(
                category,
                label,
                _find_number(narrative, expressions),
                source,
                event,
                observed_at,
            )
            if fact is not None:
                facts.append(fact)
        if re.search(
            r"\b(?:roads?|rail|airport|port|utility|power|communications?)\b.*\b(?:closed|blocked|disrupted|cut)",
            narrative,
            re.I,
        ):
            facts.append(
                ReportedFact(
                    category="utilities",
                    label="Infrastructure disruption",
                    value="Disruption reported in the source narrative",
                    status=FactStatus.PRELIMINARY,
                    source=source,
                    event_id=event.event_id,
                    observed_at=observed_at,
                    claim_id="utilities",
                )
            )
        if re.search(
            r"\b(?:rescue|search and rescue|emergency|government|authorit)",
            narrative,
            re.I,
        ):
            facts.append(
                ReportedFact(
                    category="response",
                    label="Emergency or government response",
                    value="Response action reported in the source narrative",
                    status=FactStatus.PRELIMINARY,
                    source=source,
                    event_id=event.event_id,
                    observed_at=observed_at,
                    claim_id="response",
                )
            )
        if re.search(
            r"\bno\s+(?:significant\s+)?damage\s+(?:reported|found)\b",
            narrative,
            re.I,
        ):
            facts.append(
                ReportedFact(
                    category="damage_status",
                    label="Damage status",
                    value="No damage reported in this source",
                    status=FactStatus.CONFIRMED,
                    source=source,
                    event_id=event.event_id,
                    observed_at=observed_at,
                    claim_id="damage_status",
                )
            )
        return facts

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
