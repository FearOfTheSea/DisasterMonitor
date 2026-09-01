"""Read-only projection of maintained source metadata and runtime registration state."""

from dataclasses import dataclass
from typing import Literal, TypedDict

from disaster_monitor.application.agent.models import SourceDescriptor
from disaster_monitor.application.ports.provider_registry import (
    ProviderRegistration,
    ProviderRegistryPort,
)
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.domain.disaster import Disaster

SourceAvailability = Literal["available", "unconfigured", "maintained_only"]
SourceProviderTier = Literal["primary", "secondary"]
SourceGeographicScope = Literal["country", "worldwide"]


class AdditionalSourceRuntimeState(TypedDict):
    registered: bool
    configured: bool
    provider_tier: SourceProviderTier | None
    execution_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceOperationalState:
    registered: bool
    configured: bool
    availability: SourceAvailability
    availability_detail: str
    provider_tier: SourceProviderTier | None
    execution_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceCatalogItem:
    source_id: str
    provider: str
    publisher: str
    authority: str
    information_roles: tuple[str, ...]
    supported_disasters: tuple[Disaster, ...]
    geographic_scopes: tuple[SourceGeographicScope, ...]
    country_codes: tuple[str, ...] | None
    coverage_description: str
    documentation_path: str | None
    freshness_semantics: str
    stale_threshold_seconds: int | None
    attribution: str
    limitations: tuple[str, ...]
    operational_state: SourceOperationalState


@dataclass(frozen=True, slots=True)
class SourceCatalogSnapshot:
    catalog_version: str
    sources: tuple[SourceCatalogItem, ...]


class SourceCatalogService:
    """Join catalog and runtime state without changing provider selection authority."""

    def __init__(
        self,
        catalog: SourceCatalog,
        provider_registry: ProviderRegistryPort,
        *,
        additional_runtime_sources: (
            dict[str, AdditionalSourceRuntimeState] | None
        ) = None,
    ) -> None:
        self._catalog = catalog
        self._provider_registry = provider_registry
        self._additional_runtime_sources = additional_runtime_sources or {}

    def read(self) -> SourceCatalogSnapshot:
        registrations = {
            registration.source_id: registration
            for registration in self._provider_registry.registrations
            if registration.source_id is not None
        }
        items = tuple(
            self._project(
                descriptor,
                registrations.get(descriptor.source_id),
                self._additional_runtime_sources.get(descriptor.source_id),
            )
            for descriptor in self._catalog.sources()
        )
        return SourceCatalogSnapshot(self._catalog.version, items)

    @staticmethod
    def _project(
        descriptor: SourceDescriptor,
        registration: ProviderRegistration | None,
        additional: AdditionalSourceRuntimeState | None,
    ) -> SourceCatalogItem:
        if additional is not None:
            registered = additional["registered"]
            configured = additional["configured"]
            provider_tier = additional["provider_tier"]
            execution_roles = additional["execution_roles"]
        elif registration is not None:
            registered = True
            configured = bool(registration.configured)
            tier = registration.tier
            provider_tier = tier.value
            capabilities = registration.capabilities
            execution_roles = tuple(
                sorted(str(role.value) for role in capabilities.roles)
            )
        else:
            registered = False
            configured = descriptor.configured
            provider_tier = None
            execution_roles = ()
        if registered and configured:
            availability: SourceAvailability = "available"
            availability_detail = (
                "An executable path is registered and configured. Live upstream "
                "availability is checked only when the source is requested."
            )
        elif registered:
            availability = "unconfigured"
            availability_detail = (
                "An executable path is registered but required local configuration "
                "is absent."
            )
        else:
            availability = "maintained_only"
            availability_detail = (
                "Maintained metadata has no executable disaster-provider registration."
            )
        scope = ", ".join(value.value for value in descriptor.geographic_scopes)
        countries = (
            "all maintained countries"
            if descriptor.country_codes is None
            else ", ".join(descriptor.country_codes)
        )
        return SourceCatalogItem(
            source_id=descriptor.source_id,
            provider=descriptor.display_name,
            publisher=descriptor.organization_name,
            authority=descriptor.authority_level,
            information_roles=tuple(
                role.value for role in descriptor.information_roles
            ),
            supported_disasters=descriptor.supported_disasters,
            geographic_scopes=tuple(
                scope.value for scope in descriptor.geographic_scopes
            ),
            country_codes=descriptor.country_codes,
            coverage_description=f"{descriptor.jurisdiction}; {scope}; {countries}",
            documentation_path=descriptor.documentation_path,
            freshness_semantics=descriptor.expected_freshness,
            stale_threshold_seconds=None,
            attribution=descriptor.attribution_guidance,
            limitations=descriptor.limitations,
            operational_state=SourceOperationalState(
                registered=registered,
                configured=configured,
                availability=availability,
                availability_detail=availability_detail,
                provider_tier=provider_tier,
                execution_roles=execution_roles,
            ),
        )
