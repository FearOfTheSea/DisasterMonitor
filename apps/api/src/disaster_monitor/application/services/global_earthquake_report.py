"""Explicit worldwide earthquake discovery over one registry-approved source."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from disaster_monitor.application.disaster import (
    DisasterReport,
    GlobalDisasterEvent,
    GlobalEarthquakeQuery,
    GlobalEventSelection,
    ProviderBatch,
    ReportSection,
    SelectedEventSummary,
)
from disaster_monitor.application.ports.disaster_information import (
    GlobalEarthquakeProvider,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_evidence_policy import (
    SourceEvidencePolicyError,
    validate_global_event_evidence,
)
from disaster_monitor.domain.disaster import Hazard


def _now_utc() -> datetime:
    return datetime.now(UTC)


class GlobalEarthquakeReportService:
    """Retrieve and render a bounded worldwide USGS earthquake result."""

    def __init__(
        self,
        registration: ProviderRegistration,
        *,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        capabilities = registration.capabilities
        provider = registration.provider
        if (
            not registration.configured
            or ProviderRole.EVENT_DISCOVERY not in capabilities.roles
            or Hazard.EARTHQUAKE not in capabilities.hazards
            or capabilities.country_codes is not None
            or not registration.source_id
            or not registration.allowed_hosts
            or not callable(getattr(provider, "find_global_earthquakes", None))
        ):
            raise ValueError(
                "Worldwide earthquake discovery requires one configured, "
                "registry-approved global earthquake provider."
            )
        self._registration = registration
        self._provider = cast(GlobalEarthquakeProvider, provider)
        self._clock = clock

    @classmethod
    def from_registry(
        cls, registry: ProviderRegistry, *, clock: Callable[[], datetime] = _now_utc
    ) -> "GlobalEarthquakeReportService | None":
        matches = tuple(
            registration
            for registration in registry.registrations
            if registration.configured
            and ProviderRole.EVENT_DISCOVERY in registration.capabilities.roles
            and Hazard.EARTHQUAKE in registration.capabilities.hazards
            and registration.capabilities.country_codes is None
            and callable(
                getattr(registration.provider, "find_global_earthquakes", None)
            )
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError(
                "Worldwide earthquake discovery has ambiguous provider authority."
            )
        return cls(matches[0], clock=clock)

    async def execute(self, query: GlobalEarthquakeQuery) -> DisasterReport:
        now = self._clock()
        warnings: list[str] = []
        try:
            raw_batch = await self._provider.find_global_earthquakes(query, now=now)
            batch = (
                raw_batch
                if isinstance(raw_batch, ProviderBatch)
                else ProviderBatch(tuple(raw_batch))
            )
        except Exception:
            batch = ProviderBatch()
            warnings.append(
                "The worldwide earthquake source could not be reached or returned "
                "invalid data."
            )
        accepted: list[GlobalDisasterEvent] = []
        for record in batch.records:
            try:
                accepted.append(
                    validate_global_event_evidence(
                        record,
                        source_id=self._registration.source_id or "",
                        allowed_hosts=self._registration.allowed_hosts,
                    )
                )
            except SourceEvidencePolicyError:
                warnings.append(
                    "A worldwide earthquake record violated source policy and was "
                    "excluded."
                )
        warnings.extend(issue.message for issue in batch.issues)
        selected = _select_event(tuple(accepted), query.selection)
        if selected is None:
            detail = (
                "I could not verify a matching worldwide earthquake from the "
                "configured USGS source within the bounded search window."
            )
            section = ReportSection("Situation summary", detail)
            return DisasterReport(
                message=f"## Situation summary\n{detail}",
                response_type="current_disaster_global_verification_failed",
                selected_event=None,
                retrieval_time=now,
                sources=(),
                warnings=tuple(dict.fromkeys(warnings)),
                sections=(section,),
                partial=True,
            )

        summary = SelectedEventSummary(
            event_id=selected.event_id,
            hazard=selected.hazard,
            location=selected.location,
            event_time=selected.event_time,
            latitude=selected.latitude,
            longitude=selected.longitude,
            magnitude=selected.magnitude,
            intensity=selected.intensity,
            depth_km=selected.depth_km,
            source=selected.source,
            provider_ids=selected.provider_ids,
        )
        selection_label = (
            "strongest"
            if query.selection == GlobalEventSelection.STRONGEST
            else "latest"
        )
        magnitude = (
            f" magnitude {selected.magnitude:g}"
            if selected.magnitude is not None
            else " unknown magnitude"
        )
        event_detail = (
            f"USGS identifies the {selection_label} matching worldwide earthquake "
            f"as {selected.event_id}: {selected.location}; event time "
            f"{_utc_text(selected.event_time)};{magnitude}."
        )
        limitation = (
            "This worldwide capability verifies scientific event-catalog data only. "
            "It does not claim globally complete casualties, damage, warnings, or "
            "response information."
        )
        source_line = (
            f"{selected.source.publisher} - {selected.source.title} "
            f"({selected.source.canonical_url})"
        )
        sections = (
            ReportSection("Situation summary", event_detail),
            ReportSection("Coverage boundary", limitation),
            ReportSection("Sources", f"- {source_line}"),
            ReportSection("Report freshness", f"Retrieved at {_utc_text(now)}."),
        )
        return DisasterReport(
            message="\n\n".join(
                f"## {section.title}\n{section.content}" for section in sections
            ),
            response_type="current_disaster_global_earthquake",
            selected_event=summary,
            retrieval_time=now,
            sources=(selected.source,),
            warnings=tuple(dict.fromkeys(warnings)),
            sections=sections,
            partial=True,
        )


def _select_event(
    events: tuple[GlobalDisasterEvent, ...], selection: GlobalEventSelection
) -> GlobalDisasterEvent | None:
    if not events:
        return None
    if selection == GlobalEventSelection.STRONGEST:
        return max(
            events,
            key=lambda event: (
                event.magnitude if event.magnitude is not None else float("-inf"),
                event.significance if event.significance is not None else float("-inf"),
                event.event_time,
                event.event_id,
            ),
        )
    return max(
        events,
        key=lambda event: (
            event.event_time,
            event.magnitude if event.magnitude is not None else float("-inf"),
            event.event_id,
        ),
    )


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
