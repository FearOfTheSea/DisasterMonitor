"""Bounded composites that isolate failures from individual sources."""

from collections.abc import Iterable
from datetime import datetime
from math import asin, cos, radians, sin, sqrt

from disaster_monitor.application.disaster import (
    DisasterEvent,
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    SituationReport,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError

_SAFE_MESSAGES = {
    "timeout": "The provider request timed out.",
    "network_error": "The provider network request failed.",
    "http_client_error": "The provider rejected the request.",
    "http_server_error": "The provider returned a server error.",
    "rate_limited": "The provider rate-limited the request.",
    "configuration_rejected": "The provider configuration was rejected.",
    "response_too_large": "The provider response exceeded the configured size limit.",
    "unexpected_content_type": "The provider returned an unexpected content type.",
    "malformed_json": "The provider returned malformed JSON.",
    "invalid_payload": "The provider returned an unsupported payload.",
    "empty_result": "The provider returned no matching records.",
}


def _issue(provider: str, error: DisasterProviderError) -> ProviderIssue:
    failure = error.failure
    message = _SAFE_MESSAGES.get(failure.reason_code, _SAFE_MESSAGES["invalid_payload"])
    return ProviderIssue(
        provider=provider,
        message=f"{provider}: {message}",
        reason_code=failure.reason_code,
        retryable=failure.retryable,
        http_status=failure.http_status,
        detail=failure.detail,
    )


class CompositeDisasterEventProvider:
    """Query a small ordered list of event sources and retain partial success."""

    def __init__(self, providers: Iterable[DisasterEventProvider]) -> None:
        self._providers = tuple(providers)
        self.last_diagnostics: tuple[ProviderIssue, ...] = ()
        self.last_record_counts: dict[str, int] = {}

    @property
    def providers(self) -> tuple[DisasterEventProvider, ...]:
        return self._providers

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        records: list[DisasterEvent] = []
        issues: list[ProviderIssue] = []
        self.last_record_counts = {}
        for provider in self._providers:
            name = getattr(provider, "provider_name", provider.__class__.__name__)
            try:
                result = await provider.find_recent_events(query, now=now)
                batch = (
                    result
                    if isinstance(result, ProviderBatch)
                    else ProviderBatch(tuple(result))
                )
                records.extend(batch.records)
                issues.extend(batch.issues)
                self.last_record_counts[name] = len(batch.records)
            except Exception as error:
                if isinstance(error, DisasterProviderError):
                    issues.append(_issue(name, error))
                else:
                    issues.append(
                        ProviderIssue(
                            name,
                            f"{name}: The provider returned an unsupported payload.",
                            reason_code="invalid_payload",
                        )
                    )
                self.last_record_counts[name] = 0
        self.last_diagnostics = tuple(issues)
        return ProviderBatch(
            records=cluster_physical_events(tuple(records)), issues=tuple(issues)
        )

    async def aclose(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


class CompositeSituationReportProvider:
    """Query official and supplementary situation sources with bounded fan-out."""

    def __init__(self, providers: Iterable[SituationReportProvider]) -> None:
        self._providers = tuple(providers)
        self.last_diagnostics: tuple[ProviderIssue, ...] = ()
        self.last_record_counts: dict[str, int] = {}

    @property
    def providers(self) -> tuple[SituationReportProvider, ...]:
        return self._providers

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        records: list[SituationReport] = []
        issues: list[ProviderIssue] = []
        self.last_record_counts = {}
        for provider in self._providers:
            name = getattr(provider, "provider_name", provider.__class__.__name__)
            try:
                result = await provider.get_situation_reports(event, query, now=now)
                batch = (
                    result
                    if isinstance(result, ProviderBatch)
                    else ProviderBatch(tuple(result))
                )
                records.extend(batch.records)
                issues.extend(batch.issues)
                self.last_record_counts[name] = len(batch.records)
            except Exception as error:
                if isinstance(error, DisasterProviderError):
                    issues.append(_issue(name, error))
                else:
                    issues.append(
                        ProviderIssue(
                            name,
                            f"{name}: The provider returned an unsupported payload.",
                            reason_code="invalid_payload",
                        )
                    )
                self.last_record_counts[name] = 0
        self.last_diagnostics = tuple(issues)
        return ProviderBatch(records=tuple(records), issues=tuple(issues))

    async def aclose(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


def _distance_km(first: DisasterEvent, second: DisasterEvent) -> float | None:
    if None in (first.latitude, first.longitude, second.latitude, second.longitude):
        return None
    first_lat = radians(first.latitude or 0)
    second_lat = radians(second.latitude or 0)
    delta_lat = radians((second.latitude or 0) - (first.latitude or 0))
    delta_lon = radians((second.longitude or 0) - (first.longitude or 0))
    value = (
        sin(delta_lat / 2) ** 2
        + cos(first_lat) * cos(second_lat) * sin(delta_lon / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(value))


def _same_physical_event(first: DisasterEvent, second: DisasterEvent) -> bool:
    if set(first.provider_ids) & set(second.provider_ids):
        return True
    if first.event_id == second.event_id:
        return True
    if abs((first.event_time - second.event_time).total_seconds()) > 90:
        return False
    distance = _distance_km(first, second)
    if distance is None or distance > 30:
        return False
    if (
        first.magnitude is not None
        and second.magnitude is not None
        and abs(first.magnitude - second.magnitude) > 0.5
    ):
        return False
    return True


def _preferred_event(events: list[DisasterEvent]) -> DisasterEvent:
    """Prefer the record with the richest official metadata, then USGS."""
    return max(
        events,
        key=lambda event: (
            event.magnitude is not None,
            event.latitude is not None and event.longitude is not None,
            event.significance or 0,
            "usgs:" in event.event_id.lower(),
        ),
    )


def _merge_event(events: list[DisasterEvent]) -> DisasterEvent:
    preferred = _preferred_event(events)
    richest = max(
        events,
        key=lambda event: (
            event.intensity is not None,
            event.depth_km is not None,
            event.latitude is not None and event.longitude is not None,
        ),
    )
    provider_ids = tuple(
        dict.fromkeys(
            identifier
            for event in events
            for identifier in (event.event_id, *event.provider_ids)
        )
    )
    return DisasterEvent(
        event_id=preferred.event_id,
        hazard=preferred.hazard,
        location=preferred.location,
        country=preferred.country,
        event_time=preferred.event_time,
        source=preferred.source,
        latitude=preferred.latitude,
        longitude=preferred.longitude,
        magnitude=preferred.magnitude,
        magnitude_type=preferred.magnitude_type,
        intensity=preferred.intensity or richest.intensity,
        depth_km=preferred.depth_km or richest.depth_km,
        significance=max((event.significance or 0) for event in events),
        is_aftershock=any(event.is_aftershock for event in events),
        parent_event_id=preferred.parent_event_id or richest.parent_event_id,
        sequence_id=preferred.sequence_id or richest.sequence_id,
        provider_ids=provider_ids,
    )


def cluster_physical_events(
    events: tuple[DisasterEvent, ...],
) -> tuple[DisasterEvent, ...]:
    """Collapse equivalent provider observations without merging nearby quakes."""
    clusters: list[list[DisasterEvent]] = []
    for event in events:
        for cluster in clusters:
            if any(_same_physical_event(event, item) for item in cluster):
                cluster.append(event)
                break
        else:
            clusters.append([event])
    return tuple(_merge_event(cluster) for cluster in clusters)
