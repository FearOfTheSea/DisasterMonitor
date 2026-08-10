"""Startup validation linking executable providers to maintained source metadata."""

from disaster_monitor.application.agent.models import SourceInformationRole
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)

_SITUATION_INFORMATION_ROLES = frozenset(
    {
        SourceInformationRole.OFFICIAL_WARNING,
        SourceInformationRole.CASUALTY_REPORTING,
        SourceInformationRole.PHYSICAL_DAMAGE,
        SourceInformationRole.INFRASTRUCTURE_STATUS,
        SourceInformationRole.EMERGENCY_RESPONSE,
        SourceInformationRole.HUMANITARIAN_REPORTING,
        SourceInformationRole.TSUNAMI_STATUS,
    }
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
        capabilities = registration.capabilities
        if descriptor.provider_registration_name != registration.name:
            raise ValueError(f"Source metadata drift for provider {registration.name}.")
        if descriptor.configured != registration.configured:
            raise ValueError(
                f"Configuration-state drift for provider {registration.name}."
            )
        if descriptor.requires_configuration != capabilities.requires_configuration:
            raise ValueError(
                f"Configuration-requirement drift for provider {registration.name}."
            )
        if frozenset(descriptor.supported_hazards) != capabilities.hazards:
            raise ValueError(
                f"Hazard capability drift for provider {registration.name}."
            )
        descriptor_countries = (
            None
            if descriptor.country_codes is None
            else frozenset(descriptor.country_codes)
        )
        if descriptor_countries != capabilities.country_codes:
            raise ValueError(
                f"Country capability drift for provider {registration.name}."
            )
        if frozenset(descriptor.allowed_hosts) != registration.allowed_hosts:
            raise ValueError(
                f"Network-authority drift for provider {registration.name}."
            )
        adapter_source_id = getattr(registration.provider, "source_id", None)
        adapter_hosts = getattr(registration.provider, "allowed_hosts", None)
        if not registration.allowed_hosts:
            raise ValueError(
                f"Provider {registration.name} has no approved network authority."
            )
        if adapter_source_id is None or adapter_hosts is None:
            raise ValueError(
                f"Provider {registration.name} has no adapter source policy."
            )
        if adapter_source_id != registration.source_id:
            raise ValueError(
                f"Adapter source identity drift for provider {registration.name}."
            )
        if frozenset(adapter_hosts) != registration.allowed_hosts:
            raise ValueError(
                f"Adapter network-authority drift for provider {registration.name}."
            )
        descriptor_roles = frozenset(descriptor.information_roles)
        if (
            ProviderRole.EVENT_DISCOVERY in capabilities.roles
            and SourceInformationRole.EVENT_DISCOVERY not in descriptor_roles
        ):
            raise ValueError(f"Role capability drift for provider {registration.name}.")
        if (
            ProviderRole.SITUATION_EVIDENCE in capabilities.roles
            and not descriptor_roles.intersection(_SITUATION_INFORMATION_ROLES)
        ):
            raise ValueError(f"Role capability drift for provider {registration.name}.")
        expected_tools = set()
        if ProviderRole.EVENT_DISCOVERY in capabilities.roles:
            expected_tools.add("find_disaster_event")
        if ProviderRole.SITUATION_EVIDENCE in capabilities.roles:
            expected_tools.add("retrieve_situation_evidence")
        if frozenset(descriptor.registered_tool_names) != frozenset(expected_tools):
            raise ValueError(f"Tool metadata drift for provider {registration.name}.")
    executable = {
        descriptor.source_id
        for descriptor in descriptors
        if descriptor.implementation_status == "implemented"
    }
    registered = set(registrations_by_source)
    if executable != registered:
        missing = sorted(executable - registered)
        unexpected = sorted(registered - executable)
        raise ValueError(
            "Executable source/provider mismatch: "
            f"missing providers={missing}, unexpected providers={unexpected}."
        )
