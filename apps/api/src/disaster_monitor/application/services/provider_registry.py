"""Capability-driven disaster provider registration and selection."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
    WorldwideDisasterProvider,
    WorldwideSituationProvider,
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


class ProviderRole(StrEnum):
    """Source-backed roles implemented by disaster providers."""

    EVENT_DISCOVERY = "event_discovery"
    SITUATION_EVIDENCE = "situation_evidence"


class ProviderIdentity(Protocol):
    """Source and network identity supplied by a concrete adapter."""

    source_id: str
    allowed_hosts: frozenset[str]


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Static query scope advertised by one provider registration."""

    roles: frozenset[ProviderRole]
    disasters: frozenset[Disaster]
    country_codes: frozenset[str] | None
    requires_configuration: bool = False
    geographic_scopes: frozenset[GeographicScope] = frozenset({GeographicScope.COUNTRY})
    event_scopes: frozenset[GeographicScope] = frozenset({GeographicScope.COUNTRY})
    situation_scopes: frozenset[GeographicScope] = frozenset({GeographicScope.COUNTRY})

    def supports(
        self, query: DisasterQuery | WorldwideDisasterQuery, role: ProviderRole
    ) -> bool:
        if role not in self.roles or query.disaster not in self.disasters:
            return False
        scopes = (
            self.event_scopes
            if role is ProviderRole.EVENT_DISCOVERY
            else self.situation_scopes
        )
        if isinstance(query, WorldwideDisasterQuery):
            return GeographicScope.WORLDWIDE in scopes
        return GeographicScope.COUNTRY in scopes and (
            self.country_codes is None
            or query.country.alpha3_code in self.country_codes
        )


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """A concrete provider plus capability and optional event eligibility."""

    name: str
    provider: ProviderIdentity
    capabilities: ProviderCapabilities
    tier: ProviderTier = ProviderTier.SECONDARY
    source_id: str | None = None
    configured: bool = True
    event_eligibility: Callable[[DisasterEvent], bool] | None = None
    allowed_hosts: frozenset[str] = frozenset()
    event_provider: DisasterEventProvider | None = None
    situation_provider: SituationReportProvider | None = None
    worldwide_provider: WorldwideDisasterProvider | None = None
    worldwide_situation_provider: WorldwideSituationProvider | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tier, ProviderTier):
            raise TypeError("A provider registration requires a typed provider tier.")
        roles = self.capabilities.roles
        if (
            ProviderRole.EVENT_DISCOVERY in roles
            and GeographicScope.COUNTRY in self.capabilities.event_scopes
            and self.event_provider is None
        ):
            raise ValueError(
                f"Provider {self.name} advertises event discovery "
                "without an event port."
            )
        if (
            ProviderRole.SITUATION_EVIDENCE in roles
            and GeographicScope.COUNTRY in self.capabilities.situation_scopes
            and self.situation_provider is None
        ):
            raise ValueError(
                f"Provider {self.name} advertises situation evidence "
                "without a situation port."
            )
        if (
            ProviderRole.EVENT_DISCOVERY in roles
            and GeographicScope.WORLDWIDE in self.capabilities.event_scopes
            and self.worldwide_provider is None
        ):
            raise ValueError(
                f"Provider {self.name} advertises worldwide event discovery "
                "without a worldwide port."
            )
        if (
            ProviderRole.SITUATION_EVIDENCE in roles
            and GeographicScope.WORLDWIDE in self.capabilities.situation_scopes
            and self.worldwide_situation_provider is None
        ):
            raise ValueError(
                f"Provider {self.name} advertises worldwide situation evidence "
                "without a worldwide situation port."
            )


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Eligible registrations and relevant configuration limitations."""

    registrations: tuple[ProviderRegistration, ...]
    unavailable_configuration: tuple[str, ...] = ()


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
