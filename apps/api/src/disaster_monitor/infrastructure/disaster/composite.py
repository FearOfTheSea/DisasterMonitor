"""Bounded composites that isolate failures from individual sources."""

from collections.abc import Iterable
from datetime import datetime
from typing import cast

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.domain.disaster import DisasterEvent, SituationReport
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

    def __init__(
        self, providers: Iterable[DisasterEventProvider] | ProviderRegistry
    ) -> None:
        if isinstance(providers, ProviderRegistry):
            self._registry: ProviderRegistry | None = providers
            self._providers: tuple[DisasterEventProvider, ...] = ()
        else:
            self._registry = None
            self._providers = tuple(providers)
        self.last_diagnostics: tuple[ProviderIssue, ...] = ()
        self.last_record_counts: dict[str, int] = {}

    @property
    def providers(self) -> tuple[DisasterEventProvider, ...]:
        if self._registry is None:
            return self._providers
        return tuple(
            cast(DisasterEventProvider, registration.provider)
            for registration in self._registry.registrations
            if ProviderRole.EVENT_DISCOVERY in registration.capabilities.roles
        )

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        records: list[DisasterEvent] = []
        issues: list[ProviderIssue] = []
        self.last_record_counts = {}
        providers = self._providers
        if self._registry is not None:
            providers = tuple(
                cast(DisasterEventProvider, registration.provider)
                for registration in self._registry.select(
                    query, ProviderRole.EVENT_DISCOVERY
                ).registrations
            )
        for provider in providers:
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
        return ProviderBatch(records=tuple(records), issues=tuple(issues))

    async def aclose(self) -> None:
        for provider in self.providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


class CompositeSituationReportProvider:
    """Query official and supplementary situation sources with bounded fan-out."""

    def __init__(
        self, providers: Iterable[SituationReportProvider] | ProviderRegistry
    ) -> None:
        if isinstance(providers, ProviderRegistry):
            self._registry: ProviderRegistry | None = providers
            self._providers: tuple[SituationReportProvider, ...] = ()
        else:
            self._registry = None
            self._providers = tuple(providers)
        self.last_diagnostics: tuple[ProviderIssue, ...] = ()
        self.last_record_counts: dict[str, int] = {}

    @property
    def providers(self) -> tuple[SituationReportProvider, ...]:
        if self._registry is None:
            return self._providers
        return tuple(
            cast(SituationReportProvider, registration.provider)
            for registration in self._registry.registrations
            if ProviderRole.SITUATION_EVIDENCE in registration.capabilities.roles
        )

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
        providers = self._providers
        if self._registry is not None:
            providers = tuple(
                cast(SituationReportProvider, registration.provider)
                for registration in self._registry.select(
                    query, ProviderRole.SITUATION_EVIDENCE, event=event
                ).registrations
            )
        for provider in providers:
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
        for provider in self.providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
