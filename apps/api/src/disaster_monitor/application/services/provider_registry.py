"""Capability-driven disaster provider registration and selection."""

from collections.abc import Iterable

from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.provider_registry import (
    ProviderCapabilities,
    ProviderIdentity,
    ProviderRegistration,
    ProviderRole,
    ProviderSelection,
)
from disaster_monitor.domain.disaster import Disaster, DisasterEvent, ProviderTier

__all__ = [
    "ProviderCapabilities",
    "ProviderIdentity",
    "ProviderRegistration",
    "ProviderRegistry",
    "ProviderRole",
    "ProviderSelection",
    "ProviderTier",
]


class ProviderRegistry:
    """Select provider registrations without country branches in use cases."""

    def __init__(self, registrations: Iterable[ProviderRegistration]) -> None:
        self._registrations = tuple(registrations)
        self._validate_primary_authority()

    @property
    def registrations(self) -> tuple[ProviderRegistration, ...]:
        return self._registrations

    def select(
        self,
        query: DisasterQuery | WorldwideDisasterQuery,
        role: ProviderRole,
        *,
        event: DisasterEvent | None = None,
    ) -> ProviderSelection:
        selected: list[ProviderRegistration] = []
        unavailable: list[str] = []
        for registration in self._registrations:
            if not registration.capabilities.supports(query, role):
                continue
            if not registration.configured:
                if registration.capabilities.requires_configuration:
                    unavailable.append(registration.name)
                continue
            if (
                event is not None
                and registration.event_eligibility is not None
                and not registration.event_eligibility(event)
            ):
                continue
            selected.append(registration)
        selected.sort(key=self._precedence_key)
        unavailable.sort()
        return ProviderSelection(tuple(selected), tuple(unavailable))

    def _validate_primary_authority(self) -> None:
        primary_coverage: dict[
            tuple[Disaster, ProviderRole, GeographicScope],
            list[tuple[str, frozenset[str] | None]],
        ] = {}
        for registration in self._registrations:
            if (
                not registration.configured
                or registration.tier is not ProviderTier.PRIMARY
            ):
                continue
            for role in registration.capabilities.roles:
                scopes = (
                    registration.capabilities.event_scopes
                    if role is ProviderRole.EVENT_DISCOVERY
                    else registration.capabilities.situation_scopes
                )
                for disaster in registration.capabilities.disasters:
                    for scope in scopes:
                        key = (disaster, role, scope)
                        countries = (
                            registration.capabilities.country_codes
                            if scope is GeographicScope.COUNTRY
                            else None
                        )
                        for previous, previous_countries in primary_coverage.get(
                            key, []
                        ):
                            if countries is not None and previous_countries is not None:
                                overlaps = bool(countries & previous_countries)
                            else:
                                overlaps = True
                            if overlaps:
                                raise ValueError(
                                    "Multiple configured primary providers for "
                                    f"{disaster.value}/{role.value}/{scope.value}: "
                                    f"{previous} and {registration.name}."
                                )
                        primary_coverage.setdefault(key, []).append(
                            (registration.name, countries)
                        )

    @staticmethod
    def _precedence_key(
        registration: ProviderRegistration,
    ) -> tuple[int, str, str]:
        return (
            -registration.tier.precedence,
            registration.name.casefold(),
            registration.source_id or "",
        )
