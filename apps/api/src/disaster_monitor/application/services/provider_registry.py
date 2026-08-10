"""Capability-driven disaster provider registration and selection."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.domain.disaster import DisasterEvent, Hazard


class ProviderRole(StrEnum):
    """Source-backed roles implemented by disaster providers."""

    EVENT_DISCOVERY = "event_discovery"
    SITUATION_EVIDENCE = "situation_evidence"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Static query scope advertised by one provider registration."""

    roles: frozenset[ProviderRole]
    hazards: frozenset[Hazard]
    country_codes: frozenset[str] | None
    requires_configuration: bool = False

    def supports(self, query: DisasterQuery, role: ProviderRole) -> bool:
        return (
            role in self.roles
            and query.hazard in self.hazards
            and (
                self.country_codes is None
                or query.country.alpha3_code in self.country_codes
            )
        )


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """A concrete provider plus capability and optional event eligibility."""

    name: str
    provider: object
    capabilities: ProviderCapabilities
    source_id: str | None = None
    configured: bool = True
    event_eligibility: Callable[[DisasterEvent], bool] | None = None
    allowed_hosts: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Eligible registrations and relevant configuration limitations."""

    registrations: tuple[ProviderRegistration, ...]
    unavailable_configuration: tuple[str, ...] = ()


class ProviderRegistry:
    """Select provider registrations without country branches in use cases."""

    def __init__(self, registrations: Iterable[ProviderRegistration]) -> None:
        self._registrations = tuple(registrations)

    @property
    def registrations(self) -> tuple[ProviderRegistration, ...]:
        return self._registrations

    def select(
        self,
        query: DisasterQuery,
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
        return ProviderSelection(tuple(selected), tuple(unavailable))
