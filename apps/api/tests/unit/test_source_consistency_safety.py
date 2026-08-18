from dataclasses import dataclass, replace

import pytest

from disaster_monitor.application.agent.models import (
    SourceDescriptor,
    SourceInformationRole,
)
from disaster_monitor.application.disaster import GeographicScope, ProviderBatch
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_consistency import (
    validate_provider_source_consistency,
)
from disaster_monitor.domain.disaster import Hazard


@dataclass(frozen=True)
class FakeCatalog:
    descriptor: SourceDescriptor
    version: str = "test"

    def sources(self) -> tuple[SourceDescriptor, ...]:
        return (self.descriptor,)

    def get(self, source_id: str) -> SourceDescriptor | None:
        if source_id == self.descriptor.source_id:
            return self.descriptor
        return None


@dataclass(frozen=True)
class FakeProvider:
    source_id: str
    allowed_hosts: frozenset[str]

    async def find_recent_events(self, query, *, now):
        return ProviderBatch()

    async def get_situation_reports(self, event, query, *, now):
        return ProviderBatch()


def event_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        source_id="test-events",
        organization_name="Test authority",
        display_name="Test events",
        jurisdiction="Testland",
        authority_level="national_authority",
        information_roles=(SourceInformationRole.EVENT_DISCOVERY,),
        supported_hazards=(Hazard.EARTHQUAKE,),
        country_codes=("TST",),
        geographic_scopes=(GeographicScope.COUNTRY,),
        supported_languages=("en",),
        endpoint_kind="test",
        requires_configuration=False,
        configured=True,
        expected_freshness="unknown",
        attribution_guidance="Attribute to Test authority.",
        limitations=(),
        registered_tool_names=("find_disaster_event",),
        provider_registration_name="Test event provider",
        implementation_status="implemented",
        allowed_hosts=("events.example",),
    )


def registration(
    *,
    roles: frozenset[ProviderRole] = frozenset({ProviderRole.EVENT_DISCOVERY}),
    hazards: frozenset[Hazard] = frozenset({Hazard.EARTHQUAKE}),
    countries: frozenset[str] | None = frozenset({"TST"}),
    requires_configuration: bool = False,
    allowed_hosts: frozenset[str] = frozenset({"events.example"}),
) -> ProviderRegistration:
    return ProviderRegistration(
        "Test event provider",
        FakeProvider("test-events", allowed_hosts),
        ProviderCapabilities(
            roles,
            hazards,
            countries,
            requires_configuration=requires_configuration,
        ),
        source_id="test-events",
        allowed_hosts=allowed_hosts,
        event_provider=(
            FakeProvider("test-events", allowed_hosts)
            if ProviderRole.EVENT_DISCOVERY in roles
            else None
        ),
        situation_provider=(
            FakeProvider("test-events", allowed_hosts)
            if ProviderRole.SITUATION_EVIDENCE in roles
            else None
        ),
    )


def validate(descriptor: SourceDescriptor, provider: ProviderRegistration) -> None:
    validate_provider_source_consistency(
        ProviderRegistry((provider,)),
        FakeCatalog(descriptor),
    )


def test_rejects_catalog_hazard_and_country_overclaims() -> None:
    descriptor = event_descriptor()

    with pytest.raises(ValueError, match="Hazard capability drift"):
        validate(
            replace(
                descriptor,
                supported_hazards=(Hazard.EARTHQUAKE, Hazard.FLOOD),
            ),
            registration(),
        )
    with pytest.raises(ValueError, match="Country capability drift"):
        validate(replace(descriptor, country_codes=None), registration())


def test_rejects_configuration_requirement_drift() -> None:
    with pytest.raises(ValueError, match="Configuration-requirement drift"):
        validate(
            replace(event_descriptor(), requires_configuration=True),
            registration(),
        )


def test_rejects_geographic_scope_drift() -> None:
    with pytest.raises(ValueError, match="Geographic scope capability drift"):
        validate(
            replace(
                event_descriptor(),
                geographic_scopes=(GeographicScope.WORLDWIDE,),
            ),
            registration(),
        )


def test_rejects_roles_without_typed_executable_ports() -> None:
    with pytest.raises(ValueError, match="without an event port"):
        ProviderRegistration(
            "Missing event port",
            FakeProvider("test-events", frozenset({"events.example"})),
            ProviderCapabilities(
                frozenset({ProviderRole.EVENT_DISCOVERY}),
                frozenset({Hazard.EARTHQUAKE}),
                frozenset({"TST"}),
            ),
        )
    with pytest.raises(ValueError, match="without a worldwide port"):
        ProviderRegistration(
            "Missing worldwide port",
            FakeProvider("test-events", frozenset({"events.example"})),
            ProviderCapabilities(
                frozenset({ProviderRole.EVENT_DISCOVERY}),
                frozenset({Hazard.EARTHQUAKE}),
                None,
                geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
            ),
            event_provider=FakeProvider("test-events", frozenset({"events.example"})),
        )


def test_rejects_network_authority_drift() -> None:
    descriptor = event_descriptor()

    with pytest.raises(ValueError, match="Network-authority drift"):
        validate(descriptor, registration(allowed_hosts=frozenset({"other.example"})))

    validate(descriptor, registration())


def test_rejects_missing_situation_role_and_wrong_tool_metadata() -> None:
    provider = registration(roles=frozenset({ProviderRole.SITUATION_EVIDENCE}))
    descriptor = replace(
        event_descriptor(),
        registered_tool_names=("retrieve_situation_evidence",),
    )

    with pytest.raises(ValueError, match="Role capability drift"):
        validate(descriptor, provider)

    situation_descriptor = replace(
        descriptor,
        information_roles=(SourceInformationRole.CASUALTY_REPORTING,),
    )
    with pytest.raises(ValueError, match="Tool metadata drift"):
        validate(
            replace(
                situation_descriptor,
                registered_tool_names=("find_disaster_event",),
            ),
            provider,
        )


def test_accepts_matching_situation_source_metadata() -> None:
    descriptor = replace(
        event_descriptor(),
        information_roles=(SourceInformationRole.CASUALTY_REPORTING,),
        registered_tool_names=("retrieve_situation_evidence",),
    )
    provider = registration(roles=frozenset({ProviderRole.SITUATION_EVIDENCE}))

    validate(descriptor, provider)
