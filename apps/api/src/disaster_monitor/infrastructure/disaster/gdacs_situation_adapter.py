"""Retrieve scoped, source-reported GDACS impacts for an identified event."""

import hashlib
import re
from dataclasses import replace
from datetime import datetime
from urllib.parse import urlencode

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.ports.provider_failures import ProviderFailureReason
from disaster_monitor.application.ports.provider_text import sanitize_provider_text
from disaster_monitor.application.ports.temporal_normalization import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    FactStatus,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.gdacs_situation_parsing import (
    GdacsReportObservation,
    GdacsReportPageData,
    parse_gdacs_report_page,
)
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_json,
    get_text,
)

_EVENT_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
_EVENT_TYPES = {
    Disaster.EARTHQUAKE: "EQ",
    Disaster.FLOOD: "FL",
    Disaster.WILDFIRE: "WF",
    Disaster.TROPICAL_CYCLONE: "TC",
    Disaster.VOLCANIC_ERUPTION: "VO",
}
_REPORT_PATHS = {
    "EQ": "Earthquakes",
    "FL": "Floods",
    "WF": "Wildfires",
    "TC": "Cyclones",
    "VO": "Volcanoes",
}
_HTML_FALLBACK_REASONS = frozenset(
    {
        ProviderFailureReason.TIMEOUT,
        ProviderFailureReason.NETWORK_ERROR,
        ProviderFailureReason.RATE_LIMITED,
        ProviderFailureReason.HTTP_SERVER_ERROR,
        ProviderFailureReason.ENDPOINT_MISSING,
    }
)
_OBSERVATIONS = {
    ("A", "death"): ("fatalities", "Reported deaths"),
    ("B", "injured"): ("injuries", "Reported injuries"),
    ("B", "missing"): ("missing", "Reported missing people"),
    ("B", "displaced"): ("evacuations", "Reported displaced people"),
    ("B", "rescued"): ("rescued", "Reported rescued people"),
    ("C", "houses damaged"): ("buildings_damaged", "Reported houses damaged"),
    ("C", "houses destroyed"): ("buildings_destroyed", "Reported houses destroyed"),
}


def _text(value: object) -> str:
    return sanitize_provider_text(value, limit=240) if isinstance(value, str) else ""


def _identifier(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    return _text(value)


def _event_key(event: DisasterEvent) -> tuple[str, str] | None:
    event_type = _EVENT_TYPES.get(event.disaster)
    if event_type is None:
        return None
    keys = {
        match.group(1)
        for identifier in (event.event_id, *event.provider_ids)
        if (
            match := re.fullmatch(
                rf"gdacs:{event_type.lower()}:(\d+)(?::\d+)?", identifier
            )
        )
    }
    return (event_type, next(iter(keys))) if len(keys) == 1 else None


def _episode_id(event: DisasterEvent, event_type: str, identifier: str) -> str | None:
    pattern = re.compile(rf"gdacs:{event_type.lower()}:{identifier}:(\d+)")
    episode_ids = {
        match.group(1)
        for value in (event.event_id, *event.provider_ids)
        if (match := pattern.fullmatch(value))
    }
    return next(iter(episode_ids)) if len(episode_ids) == 1 else None


def _report_params(
    event_type: str, identifier: str, episode_id: str | None
) -> dict[str, str]:
    params = {"detail": "true", "eventtype": event_type, "eventid": identifier}
    if episode_id is not None:
        params["episodeid"] = episode_id
    return params


def _report_url(event_type: str, identifier: str, episode_id: str | None) -> str:
    return (
        f"https://www.gdacs.org/{_REPORT_PATHS[event_type]}/report.aspx?"
        + urlencode(_report_params(event_type, identifier, episode_id))
    )


class GdacsSituationAdapter:
    """Admit Sendai observations, never modelled exposure or inferred totals."""

    provider_name = "GDACS situation reports"
    source_id = "gdacs-situation-reports"
    allowed_hosts = frozenset({"www.gdacs.org"})

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._max_response_bytes = max_response_bytes

    @staticmethod
    def supports_event(event: DisasterEvent) -> bool:
        return _event_key(event) is not None

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        key = _event_key(event)
        if (
            key is None
            or event.disaster != query.disaster
            or event.country != query.country
        ):
            return ProviderBatch()
        event_type, identifier = key
        params = {"eventtype": event_type, "eventid": identifier}
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters=params,
            rights_id="gdacs-terms-of-use",
            retrieved_at=now,
        )
        try:
            payload = await get_json(
                self._client,
                _EVENT_URL,
                allowed_hosts=self.allowed_hosts,
                params=params,
                max_bytes=self._max_response_bytes,
                provider_name=self.provider_name,
                capture=capture,
                accepted_content_types=frozenset({""}),
            )
        except DisasterProviderError as error:
            if error.failure.reason_code not in _HTML_FALLBACK_REASONS:
                raise
            return await self._get_report_page(
                event,
                query,
                now=now,
                event_type=event_type,
                identifier=identifier,
                original_error=error,
            )
        properties = payload.get("properties") if isinstance(payload, dict) else None
        if not isinstance(properties, dict) or (
            str(properties.get("eventid")) != identifier
            or properties.get("eventtype") != event_type
            or properties.get("iso3") != query.country.alpha3_code
        ):
            return self._issue(
                "invalid_payload",
                "Event details did not match the selected event and country.",
            )
        rows = properties.get("sendai")
        if not isinstance(rows, list):
            return self._issue(
                "invalid_payload",
                "The event detail response omitted the observed-impact list.",
            )
        source = SourceReference(
            source_id=self.source_id,
            publisher="GDACS; source: "
            + (_text(properties.get("source")) or "not specified"),
            title=_text(properties.get("name")) or "GDACS event impact observations",
            canonical_url=_report_url(
                event_type,
                identifier,
                _identifier(properties.get("episodeid"))
                or _episode_id(event, event_type, identifier),
            ),
            published_at=None,
            updated_at=normalize_timestamp(properties.get("datemodified")),
            retrieved_at=now,
            authority=SourceAuthority.SECONDARY,
            snapshot_id=capture.snapshot.snapshot_id
            if capture and capture.snapshot
            else None,
        )
        facts = tuple(
            fact
            for row in rows[:200]
            if (fact := _observation(row, source, event, query, now)) is not None
        )
        if not facts:
            return self._issue(
                "empty_result",
                "No usable observed impacts were returned for this event; "
                "missing figures are unknown.",
            )
        issues: tuple[ProviderIssue, ...] = ()
        if len(facts) != len(rows):
            issues = (
                ProviderIssue(
                    self.provider_name,
                    "GDACS: Some impact rows were outside the supported "
                    "observation scope and were omitted.",
                    reason_code="invalid_record",
                ),
            )
        report = SituationReport(
            source=source,
            narrative=(
                "GDACS reports the following local impact observations. Each figure "
                "retains its reported location and observation period; figures are "
                "not summed into a national total. These are secondary reports, "
                "not independent confirmation or modelled losses."
            ),
            facts=facts,
            event_id=f"gdacs:{event_type.lower()}:{identifier}",
            reported_event_time=normalize_timestamp(properties.get("fromdate")),
            country_codes=(query.country.alpha3_code,),
            disaster=query.disaster,
        )
        return ProviderBatch(records=(report,), issues=issues)

    async def _get_report_page(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
        event_type: str,
        identifier: str,
        original_error: DisasterProviderError,
    ) -> ProviderBatch[SituationReport]:
        episode_id = _episode_id(event, event_type, identifier)
        params = _report_params(event_type, identifier, episode_id)
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"representation": "report_page", **params},
            rights_id="gdacs-terms-of-use",
            retrieved_at=now,
        )
        try:
            html = await get_text(
                self._client,
                f"https://www.gdacs.org/{_REPORT_PATHS[event_type]}/report.aspx",
                allowed_hosts=self.allowed_hosts,
                params=params,
                max_bytes=self._max_response_bytes,
                provider_name=self.provider_name,
                capture=capture,
            )
            page = parse_gdacs_report_page(html, episode_id=episode_id, now=now)
        except DisasterProviderError as error:
            raise error from original_error
        if page is None:
            raise DisasterProviderResponseError(
                "The GDACS report page did not contain a dated Sendai observation "
                "table for the selected event.",
                reason_code=ProviderFailureReason.INVALID_PAYLOAD,
            ) from original_error
        report_url = _report_url(event_type, identifier, episode_id)
        source = SourceReference(
            source_id=self.source_id,
            publisher="GDACS; official report page",
            title="GDACS event impact observations",
            canonical_url=report_url,
            published_at=page.assessed_at,
            updated_at=page.assessed_at,
            retrieved_at=now,
            authority=SourceAuthority.SECONDARY,
            snapshot_id=capture.snapshot.snapshot_id
            if capture and capture.snapshot
            else None,
        )
        observations = page.observations[:200]
        facts = tuple(
            fact
            for observation in observations
            if (fact := _report_observation(observation, source, event, query, page))
            is not None
        )
        if not facts:
            return self._issue(
                "empty_result",
                "The official report page contained no usable observed impacts; "
                "missing figures are unknown.",
            )
        issues = [
            ProviderIssue(
                self.provider_name,
                "GDACS event-detail JSON was unavailable; the official report page "
                "fallback supplied dated Sendai observations.",
                reason_code="html_fallback",
            )
        ]
        if len(facts) != len(observations):
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    "GDACS: Some report-page rows were outside the supported "
                    "observation scope and were omitted.",
                    reason_code="invalid_record",
                )
            )
        report = SituationReport(
            source=source,
            narrative=(
                "GDACS reports the following local impact observations from its "
                "official report page. The page supplies an episode period but not "
                "row-level periods; figures are not summed into a national total. "
                "These are secondary reports, not independent confirmation or "
                "modelled losses."
            ),
            facts=facts,
            event_id=f"gdacs:{event_type.lower()}:{identifier}",
            reported_event_time=page.episode_start or event.event_time,
            country_codes=(query.country.alpha3_code,),
            disaster=query.disaster,
        )
        return ProviderBatch(records=(report,), issues=tuple(issues))

    def _issue(self, reason: str, message: str) -> ProviderBatch[SituationReport]:
        return ProviderBatch(
            issues=(
                ProviderIssue(
                    self.provider_name, f"GDACS: {message}", reason_code=reason
                ),
            )
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _observation(
    row: object,
    source: SourceReference,
    event: DisasterEvent,
    query: DisasterQuery,
    now: datetime,
) -> ReportedFact | None:
    if not isinstance(row, dict):
        return None
    meaning = _OBSERVATIONS.get(
        (_text(row.get("sendaitype")), _text(row.get("sendainame")))
    )
    country_names = {
        query.country.canonical_name.casefold(),
        *(name.casefold() for name in query.country.aliases),
    }
    value = row.get("sendaivalue")
    region = _text(row.get("region"))
    published = normalize_timestamp(row.get("dateinsert"))
    onset = normalize_timestamp(row.get("onset_date"))
    end = normalize_timestamp(row.get("expires_date"))
    if (
        meaning is None
        or _text(row.get("country")).casefold() not in country_names
        or not isinstance(value, str)
        or not re.fullmatch(r"\d{1,12}", value)
        or not region
        or published is None
        or published > now
        or onset is None
        or end is None
        or end < onset
        or onset > now
    ):
        return None
    category, label = meaning
    period = (
        onset.isoformat().replace("+00:00", "Z")
        + " to "
        + end.isoformat().replace("+00:00", "Z")
    )
    identity = f"{event.event_id}|{category}|{region.casefold()}|{period}"
    return ReportedFact(
        category=category,
        label=f"{label} — {region}",
        value=f"{int(value)} (reported period {period})",
        status=FactStatus.PRELIMINARY,
        source=replace(source, published_at=published, updated_at=published),
        event_id=event.event_id,
        observed_at=onset,
        claim_id="gdacs-observation:"
        + hashlib.sha256(identity.encode()).hexdigest()[:24],
    )


def _report_observation(
    observation: GdacsReportObservation,
    source: SourceReference,
    event: DisasterEvent,
    query: DisasterQuery,
    page: GdacsReportPageData,
) -> ReportedFact | None:
    meaning = _OBSERVATIONS.get((observation.indicator_type, observation.name))
    country_names = {
        query.country.canonical_name.casefold(),
        *(name.casefold() for name in query.country.aliases),
    }
    if (
        meaning is None
        or observation.country.casefold() not in country_names
        or not re.fullmatch(r"\d{1,12}", observation.value)
        or not observation.region
    ):
        return None
    category, label = meaning
    if page.episode_start is not None and page.episode_end is not None:
        period = (
            f"{page.episode_start.date().isoformat()} to "
            f"{page.episode_end.date().isoformat()}"
        )
        period_text = (
            f"reported episode period {period}; row-level period not specified "
            "on report page"
        )
        observed_at = page.episode_start
    else:
        period = f"assessment {page.assessed_at.date().isoformat()}"
        period_text = (
            f"reported by GDACS on {page.assessed_at.date().isoformat()}; "
            "row-level period not specified on report page"
        )
        observed_at = page.assessed_at
    identity = f"{event.event_id}|{category}|{observation.region.casefold()}|{period}"
    return ReportedFact(
        category=category,
        label=f"{label} — {observation.region}",
        value=f"{int(observation.value)} ({period_text})",
        status=FactStatus.PRELIMINARY,
        source=replace(
            source, published_at=page.assessed_at, updated_at=page.assessed_at
        ),
        event_id=event.event_id,
        observed_at=observed_at,
        claim_id="gdacs-report-observation:"
        + hashlib.sha256(identity.encode()).hexdigest()[:24],
    )
