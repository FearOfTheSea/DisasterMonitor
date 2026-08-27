"""Bounded composites that isolate failures from individual sources."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.ports.provider_registry import (
    ProviderRegistration,
    ProviderRegistryPort,
    ProviderRole,
)
from disaster_monitor.application.ports.source_evidence import (
    EventEvidenceValidator,
    SituationEvidenceValidator,
    SourceEvidencePolicyError,
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
    "source_policy_violation": "The provider record violated source policy.",
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


def _policy_issue(provider: str, error: SourceEvidencePolicyError) -> ProviderIssue:
    return ProviderIssue(
        provider=provider,
        message=f"{provider}: {_SAFE_MESSAGES['source_policy_violation']}",
        reason_code="source_policy_violation",
        detail=str(error),
    )


def _safe_batch_issues(
    provider: str, value: tuple[object, ...]
) -> tuple[ProviderIssue, ...]:
    issues = tuple(item for item in value if isinstance(item, ProviderIssue))
    if len(issues) == len(value):
        return issues
    return (
        *issues,
        ProviderIssue(
            provider,
            f"{provider}: {_SAFE_MESSAGES['invalid_payload']}",
            reason_code="invalid_payload",
        ),
    )


class CompositeDisasterEventProvider:
    """Query a small ordered list of event sources and retain partial success."""

    def __init__(
        self,
        providers: Iterable[DisasterEventProvider] | ProviderRegistryPort,
        *,
        validate: EventEvidenceValidator | None = None,
    ) -> None:
        if isinstance(providers, ProviderRegistryPort):
            if validate is None:
                raise ValueError("Registry-backed event providers require validation.")
            self._registry: ProviderRegistryPort | None = providers
            self._providers: tuple[DisasterEventProvider, ...] = ()
        else:
            self._registry = None
            self._providers = tuple(providers)
        self._validate = validate
        self.last_diagnostics: tuple[ProviderIssue, ...] = ()
        self.last_record_counts: dict[str, int] = {}

    @property
    def providers(self) -> tuple[DisasterEventProvider, ...]:
        if self._registry is None:
            return self._providers
        return tuple(
            registration.event_provider
            for registration in self._registry.registrations
            if ProviderRole.EVENT_DISCOVERY in registration.capabilities.roles
            and registration.event_provider is not None
        )

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        records: list[DisasterEvent] = []
        issues: list[ProviderIssue] = []
        self.last_record_counts = {}
        selected: tuple[
            tuple[ProviderRegistration | None, DisasterEventProvider], ...
        ] = tuple((None, provider) for provider in self._providers)
        if self._registry is not None:
            selected = tuple(
                (registration, registration.event_provider)
                for registration in self._registry.select(
                    query, ProviderRole.EVENT_DISCOVERY
                ).registrations
                if registration.event_provider is not None
            )
        for registration, provider in selected:
            name = (
                registration.name
                if registration is not None
                else provider.__class__.__name__
            )
            try:
                result = await provider.find_recent_events(query, now=now)
                batch = (
                    result
                    if isinstance(result, ProviderBatch)
                    else ProviderBatch(tuple(result))
                )
                accepted: list[DisasterEvent] = []
                for record in batch.records:
                    if registration is None:
                        if not isinstance(record, DisasterEvent):
                            raise SourceEvidencePolicyError(
                                "The event provider returned a wrong record type."
                            )
                        accepted.append(record)
                        continue
                    try:
                        assert self._validate is not None
                        accepted_record = self._validate(
                            record,
                            query,
                            source_id=registration.source_id or "",
                            allowed_hosts=registration.allowed_hosts,
                        )
                        accepted.append(
                            replace(accepted_record, provider_tier=registration.tier)
                        )
                    except SourceEvidencePolicyError as error:
                        issues.append(_policy_issue(name, error))
                records.extend(accepted)
                issues.extend(_safe_batch_issues(name, tuple(batch.issues)))
                self.last_record_counts[name] = len(accepted)
            except Exception as error:
                if isinstance(error, DisasterProviderError):
                    issues.append(_issue(name, error))
                elif isinstance(error, SourceEvidencePolicyError):
                    issues.append(_policy_issue(name, error))
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
        self,
        providers: Iterable[SituationReportProvider] | ProviderRegistryPort,
        *,
        validate: SituationEvidenceValidator | None = None,
    ) -> None:
        if isinstance(providers, ProviderRegistryPort):
            if validate is None:
                raise ValueError(
                    "Registry-backed situation providers require validation."
                )
            self._registry: ProviderRegistryPort | None = providers
            self._providers: tuple[SituationReportProvider, ...] = ()
        else:
            self._registry = None
            self._providers = tuple(providers)
        self._validate = validate
        self.last_diagnostics: tuple[ProviderIssue, ...] = ()
        self.last_record_counts: dict[str, int] = {}

    @property
    def providers(self) -> tuple[SituationReportProvider, ...]:
        if self._registry is None:
            return self._providers
        return tuple(
            registration.situation_provider
            for registration in self._registry.registrations
            if ProviderRole.SITUATION_EVIDENCE in registration.capabilities.roles
            and registration.situation_provider is not None
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
        selected: tuple[
            tuple[ProviderRegistration | None, SituationReportProvider], ...
        ] = tuple((None, provider) for provider in self._providers)
        if self._registry is not None:
            selected = tuple(
                (
                    registration,
                    registration.situation_provider,
                )
                for registration in self._registry.select(
                    query, ProviderRole.SITUATION_EVIDENCE, event=event
                ).registrations
                if registration.situation_provider is not None
            )
        for registration, provider in selected:
            name = (
                registration.name
                if registration is not None
                else provider.__class__.__name__
            )
            try:
                result = await provider.get_situation_reports(event, query, now=now)
                batch = (
                    result
                    if isinstance(result, ProviderBatch)
                    else ProviderBatch(tuple(result))
                )
                accepted: list[SituationReport] = []
                for record in batch.records:
                    if registration is None:
                        if not isinstance(record, SituationReport):
                            raise SourceEvidencePolicyError(
                                "The situation provider returned a wrong record type."
                            )
                        accepted.append(record)
                        continue
                    try:
                        assert self._validate is not None
                        accepted.append(
                            self._validate(
                                record,
                                query,
                                source_id=registration.source_id or "",
                                allowed_hosts=registration.allowed_hosts,
                            )
                        )
                    except SourceEvidencePolicyError as error:
                        issues.append(_policy_issue(name, error))
                records.extend(accepted)
                issues.extend(_safe_batch_issues(name, tuple(batch.issues)))
                self.last_record_counts[name] = len(accepted)
            except Exception as error:
                if isinstance(error, DisasterProviderError):
                    issues.append(_issue(name, error))
                elif isinstance(error, SourceEvidencePolicyError):
                    issues.append(_policy_issue(name, error))
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
