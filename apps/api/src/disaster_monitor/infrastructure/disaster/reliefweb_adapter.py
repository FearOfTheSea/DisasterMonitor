"""Supplementary ReliefWeb situation-report adapter."""

import html
import re
from datetime import datetime, timedelta

import httpx

from disaster_monitor.application.disaster import (
    DisasterEvent,
    DisasterQuery,
    FactStatus,
    ProviderBatch,
    ReportedFact,
    SituationReport,
    SourceReference,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
    sanitize_provider_text,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import get_json

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

    def __init__(
        self,
        *,
        app_name: str = "disaster-monitor-local",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._app_name = app_name
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        payload = await get_json(
            self._client,
            RELIEFWEB_REPORTS_URL,
            params={
                "appname": self._app_name,
                "query[value]": f"{query.hazard} {query.geography}",
                "limit": 20,
                "sort[]": "date.created:desc",
            },
            max_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise DisasterProviderResponseError(
                "The ReliefWeb response had no report list."
            )
        reports: list[SituationReport] = []
        minimum_date = now - timedelta(days=query.time_window_days)
        for item in payload["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("fields"), dict):
                continue
            fields = item["fields"]
            title = _text(fields.get("title"))
            url = _text(fields.get("url"))
            if not title or not url or not url.startswith("https://"):
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
                publisher="ReliefWeb",
                title=title,
                canonical_url=url,
                published_at=published_at,
                updated_at=updated_at,
                retrieved_at=now,
            )
            raw_body = fields.get("body") or fields.get("description") or ""
            narrative = sanitize_provider_text(html.unescape(_text(raw_body)))
            facts = self._extract_facts(narrative, source, event, published_at)
            reports.append(
                SituationReport(
                    source=source,
                    narrative=narrative,
                    facts=tuple(facts),
                    event_id=event.event_id,
                )
            )
        return ProviderBatch(records=tuple(reports))

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
