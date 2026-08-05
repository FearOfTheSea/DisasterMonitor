"""Bounded composites that isolate failures from individual sources."""

from collections.abc import Iterable
from datetime import datetime

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


class CompositeDisasterEventProvider:
    """Query a small ordered list of event sources and retain partial success."""

    def __init__(self, providers: Iterable[DisasterEventProvider]) -> None:
        self._providers = tuple(providers)

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        records: list[DisasterEvent] = []
        issues: list[ProviderIssue] = []
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
            except Exception:
                issues.append(
                    ProviderIssue(name, f"{name} did not return usable event data.")
                )
        return ProviderBatch(records=tuple(records), issues=tuple(issues))

    async def aclose(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


class CompositeSituationReportProvider:
    """Query official and supplementary situation sources with bounded fan-out."""

    def __init__(self, providers: Iterable[SituationReportProvider]) -> None:
        self._providers = tuple(providers)

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        records: list[SituationReport] = []
        issues: list[ProviderIssue] = []
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
            except Exception:
                issues.append(
                    ProviderIssue(name, f"{name} did not return usable situation data.")
                )
        return ProviderBatch(records=tuple(records), issues=tuple(issues))

    async def aclose(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
