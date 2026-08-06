"""Startup validation linking executable providers to maintained source metadata."""

from disaster_monitor.application.agent.models import SourceInformationRole
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)


def validate_provider_source_consistency(
    registry: ProviderRegistry, catalog: SourceCatalog
) -> None:
    descriptors = catalog.sources()
    source_ids = [item.source_id for item in descriptors]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("The source catalog contains duplicate source IDs.")
    by_id = {item.source_id: item for item in descriptors}
    registrations_by_source = {}
    for registration in registry.registrations:
        if not registration.source_id or registration.source_id not in by_id:
            raise ValueError(
                f"Provider {registration.name} has no matching source descriptor."
            )
        if registration.source_id in registrations_by_source:
            raise ValueError("More than one provider uses the same source descriptor.")
        registrations_by_source[registration.source_id] = registration
        descriptor = by_id[registration.source_id]
        if descriptor.provider_registration_name != registration.name:
            raise ValueError(f"Source metadata drift for provider {registration.name}.")
        if descriptor.configured != registration.configured:
            raise ValueError(
                f"Configuration-state drift for provider {registration.name}."
            )
        if not registration.capabilities.hazards.issubset(
            frozenset(descriptor.supported_hazards)
        ):
            raise ValueError(
                f"Hazard capability drift for provider {registration.name}."
            )
        if (
            registration.capabilities.country_codes is not None
            and descriptor.country_codes is not None
            and not registration.capabilities.country_codes.issubset(
                frozenset(descriptor.country_codes)
            )
        ):
            raise ValueError(
                f"Country capability drift for provider {registration.name}."
            )
        required_roles = set()
        if ProviderRole.EVENT_DISCOVERY in registration.capabilities.roles:
            required_roles.add(SourceInformationRole.EVENT_DISCOVERY)
        if ProviderRole.SITUATION_EVIDENCE in registration.capabilities.roles:
            required_roles.update(
                {
                    SourceInformationRole.CASUALTY_REPORTING,
                    SourceInformationRole.PHYSICAL_DAMAGE,
                    SourceInformationRole.OFFICIAL_WARNING,
                    SourceInformationRole.HUMANITARIAN_REPORTING,
                    SourceInformationRole.TSUNAMI_STATUS,
                }
                & set(descriptor.information_roles)
            )
        if ProviderRole.EVENT_DISCOVERY in registration.capabilities.roles and not (
            required_roles & set(descriptor.information_roles)
        ):
            raise ValueError(f"Role capability drift for provider {registration.name}.")
    executable = {
        descriptor.source_id
        for descriptor in descriptors
        if descriptor.implementation_status == "implemented"
    }
    if executable != set(registrations_by_source):
        missing = sorted(executable - set(registrations_by_source))
        raise ValueError(f"Executable source descriptors lack providers: {missing}")
