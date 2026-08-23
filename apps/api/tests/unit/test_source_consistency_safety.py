from dataclasses import dataclass, replace

import pytest

from disaster_monitor.application.agent.models import (
    SourceDescriptor,
    SourceInformationRole,
)
from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    ProviderBatch,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_consistency import (
    validate_provider_source_consistency,
)
from disaster_monitor.domain.disaster import Country, Disaster, GeographicArea
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)


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

    async def find_worldwide_events(self, query, *, now):
        return ProviderBatch()


def event_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        source_id="test-events",
        organization_name="Test authority",
        display_name="Test events",
        jurisdiction="Testland",
        authority_level="national_authority",
        information_roles=(SourceInformationRole.EVENT_DISCOVERY,),
        supported_disasters=(Disaster.EARTHQUAKE,),
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
    disasters: frozenset[Disaster] = frozenset({Disaster.EARTHQUAKE}),
    countries: frozenset[str] | None = frozenset({"TST"}),
    requires_configuration: bool = False,
    allowed_hosts: frozenset[str] = frozenset({"events.example"}),
) -> ProviderRegistration:
    return ProviderRegistration(
        "Test event provider",
        FakeProvider("test-events", allowed_hosts),
        ProviderCapabilities(
            roles,
            disasters,
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


def test_rejects_catalog_disaster_and_country_overclaims() -> None:
    descriptor = event_descriptor()

    with pytest.raises(ValueError, match="Disaster capability drift"):
        validate(
            replace(
                descriptor,
                supported_disasters=(Disaster.EARTHQUAKE, Disaster.FLOOD),
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
                frozenset({Disaster.EARTHQUAKE}),
                frozenset({"TST"}),
            ),
        )


def test_worldwide_only_and_mixed_scope_ports_do_not_form_a_cartesian_product() -> None:
    provider = FakeProvider("worldwide", frozenset({"events.example"}))
    worldwide_only = ProviderRegistration(
        "Worldwide only",
        provider,
        ProviderCapabilities(
            frozenset({ProviderRole.EVENT_DISCOVERY}),
            frozenset({Disaster.FLOOD}),
            None,
            geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
            event_scopes=frozenset({GeographicScope.WORLDWIDE}),
        ),
        worldwide_provider=provider,
    )
    country_query = DisasterQuery(
        Disaster.FLOOD,
        Country("TST", "Testland", (), GeographicArea(0, 1, 0, 1)),
        "recent",
        (),
    )
    assert worldwide_only.capabilities.supports(
        WorldwideDisasterQuery(Disaster.FLOOD), ProviderRole.EVENT_DISCOVERY
    )
    assert not worldwide_only.capabilities.supports(
        country_query, ProviderRole.EVENT_DISCOVERY
    )

    mixed = ProviderRegistration(
        "Worldwide events and country situations",
        provider,
        ProviderCapabilities(
            frozenset({ProviderRole.EVENT_DISCOVERY, ProviderRole.SITUATION_EVIDENCE}),
            frozenset({Disaster.FLOOD}),
            None,
            geographic_scopes=frozenset(
                {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
            ),
            event_scopes=frozenset({GeographicScope.WORLDWIDE}),
            situation_scopes=frozenset({GeographicScope.COUNTRY}),
        ),
        situation_provider=provider,
        worldwide_provider=provider,
    )
    assert mixed.capabilities.supports(
        WorldwideDisasterQuery(Disaster.FLOOD), ProviderRole.EVENT_DISCOVERY
    )
    assert not mixed.capabilities.supports(
        WorldwideDisasterQuery(Disaster.FLOOD), ProviderRole.SITUATION_EVIDENCE
    )
    with pytest.raises(ValueError, match="without a worldwide port"):
        ProviderRegistration(
            "Missing worldwide port",
            FakeProvider("test-events", frozenset({"events.example"})),
            ProviderCapabilities(
                frozenset({ProviderRole.EVENT_DISCOVERY}),
                frozenset({Disaster.EARTHQUAKE}),
                None,
                geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
                event_scopes=frozenset({GeographicScope.WORLDWIDE}),
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


def test_accepts_map_layers_as_typed_situation_evidence() -> None:
    descriptor = replace(
        event_descriptor(),
        information_roles=(SourceInformationRole.MAP_LAYERS,),
        registered_tool_names=("retrieve_situation_evidence",),
    )
    provider = registration(roles=frozenset({ProviderRole.SITUATION_EVIDENCE}))

    validate(descriptor, provider)


def test_packaged_copernicus_rapid_mapping_metadata_is_map_evidence_only() -> None:
    descriptor = StaticSourceCatalog().get("copernicus-rapid-mapping-landslides")

    assert descriptor is not None
    assert descriptor.provider_registration_name == (
        "Copernicus EMS Rapid Mapping landslides"
    )
    assert descriptor.information_roles == (SourceInformationRole.MAP_LAYERS,)
    assert descriptor.supported_disasters == (Disaster.LANDSLIDE,)
    assert descriptor.registered_tool_names == ("retrieve_situation_evidence",)
    assert descriptor.authority_level == "secondary"
    assert any("Risk and Recovery" in item for item in descriptor.limitations)
    assert any("identity" in item for item in descriptor.limitations)


def test_packaged_ibtracs_metadata_is_track_reconciliation_only() -> None:
    descriptor = StaticSourceCatalog().get("noaa-ibtracs-tracks")

    assert descriptor is not None
    assert descriptor.provider_registration_name == (
        "NOAA IBTrACS track reconciliation"
    )
    assert set(descriptor.information_roles) == {
        SourceInformationRole.SCIENTIFIC_EVENT_VERIFICATION,
        SourceInformationRole.MAP_LAYERS,
    }
    assert descriptor.supported_disasters == (Disaster.TROPICAL_CYCLONE,)
    assert descriptor.registered_tool_names == ("retrieve_situation_evidence",)
    assert descriptor.authority_level == "scientific_authority"
    assert any("not a live-event" in item for item in descriptor.limitations)
    assert any("not independent" in item for item in descriptor.limitations)


def test_packaged_gfm_source_metadata_declares_the_registered_authorities() -> None:
    descriptor = StaticSourceCatalog().get("cems-gfm-floods")

    assert descriptor is not None
    assert descriptor.provider_registration_name == "CEMS Global Flood Monitoring (GFM)"
    assert descriptor.authority_level == "scientific_authority"
    assert descriptor.supported_disasters == (Disaster.FLOOD,)
    assert descriptor.country_codes is None
    assert set(descriptor.allowed_hosts) == {
        "data.eodc.eu",
        "stac.eodc.eu",
        "titiler.services.eodc.eu",
    }


def test_packaged_smithsonian_source_metadata_declares_the_registered_authorities() -> (
    None
):
    descriptor = StaticSourceCatalog().get("smithsonian-usgs-volcanic-activity")

    assert descriptor is not None
    assert descriptor.provider_registration_name == (
        "Smithsonian / USGS Weekly Volcanic Activity Report"
    )
    assert descriptor.authority_level == "scientific_authority"
    assert descriptor.supported_disasters == (Disaster.VOLCANIC_ERUPTION,)
    assert descriptor.country_codes is None
    assert descriptor.requires_configuration is False
    assert descriptor.configured is True
    assert set(descriptor.geographic_scopes) == {
        GeographicScope.COUNTRY,
        GeographicScope.WORLDWIDE,
    }
    assert set(descriptor.allowed_hosts) == {
        "volcano.si.edu",
        "webservices.volcano.si.edu",
    }
    assert descriptor.registered_tool_names == ("find_disaster_event",)
    assert any("not a comprehensive list" in item for item in descriptor.limitations)
    assert any("casualties" in item for item in descriptor.limitations)


@pytest.mark.parametrize(
    ("source_id", "name", "disaster", "host"),
    (
        (
            "nasa-eonet-wildfires",
            "NASA EONET Wildfires",
            Disaster.WILDFIRE,
            "eonet.gsfc.nasa.gov",
        ),
        (
            "nasa-coolr-landslides",
            "NASA COOLR Landslides",
            Disaster.LANDSLIDE,
            "gis.earthdata.nasa.gov",
        ),
    ),
)
def test_packaged_nasa_source_metadata_declares_registered_authority(
    source_id: str, name: str, disaster: Disaster, host: str
) -> None:
    descriptor = StaticSourceCatalog().get(source_id)

    assert descriptor is not None
    assert descriptor.provider_registration_name == name
    assert descriptor.supported_disasters == (disaster,)
    assert descriptor.country_codes is None
    assert set(descriptor.allowed_hosts) == {host}
    assert set(descriptor.registered_tool_names) == {"find_disaster_event"}
    assert descriptor.requires_configuration is False
    assert set(descriptor.geographic_scopes) == {
        GeographicScope.COUNTRY,
        GeographicScope.WORLDWIDE,
    }
