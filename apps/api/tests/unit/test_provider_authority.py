from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    ProviderBatch,
)
from disaster_monitor.application.services.event_resolution import DefaultEventPolicy
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
    ProviderTier,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventMeasurement,
    MeasurementKind,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.composition import build_current_disaster_report
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
JAPAN = StaticCountryCatalog().get_by_alpha3("JPN")
assert JAPAN is not None


class StaticEventProvider:
    def __init__(self, source_id: str, records: tuple[DisasterEvent, ...]) -> None:
        self.source_id = source_id
        self.allowed_hosts = frozenset({"example.test"})
        self.records = records

    async def find_recent_events(self, query: DisasterQuery, *, now: datetime):
        return ProviderBatch(self.records)


def _query() -> DisasterQuery:
    return DisasterQuery(Disaster.FLOOD, JAPAN, "recent", ("latest",))


def _source(source_id: str) -> SourceReference:
    return SourceReference(
        source_id,
        source_id,
        "Provider event",
        f"https://example.test/{source_id}",
        NOW,
        NOW,
        NOW,
    )


def _event(
    source_id: str,
    *,
    location: str = "Japan",
    magnitude: float | None = None,
    event_time: datetime = NOW,
) -> DisasterEvent:
    source = _source(source_id)
    measurements = (
        (EventMeasurement(MeasurementKind.MAGNITUDE, magnitude, source=source),)
        if magnitude is not None
        else ()
    )
    return DisasterEvent(
        event_id="flood:shared",
        disaster=Disaster.FLOOD,
        location=location,
        country=JAPAN,
        event_time=event_time,
        source=source,
        geometry=point_event_geometry(35.0, 139.0, source),
        measurements=measurements,
        provider_ids=("flood:shared",),
    )


def _registration(
    name: str,
    provider: StaticEventProvider,
    *,
    tier: ProviderTier,
) -> ProviderRegistration:
    return ProviderRegistration(
        name,
        provider,
        ProviderCapabilities(
            roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
            disasters=frozenset({Disaster.FLOOD}),
            country_codes=frozenset({"JPN"}),
            event_scopes=frozenset({GeographicScope.COUNTRY}),
        ),
        tier=tier,
        source_id=provider.source_id,
        allowed_hosts=provider.allowed_hosts,
        event_provider=provider,
    )


def test_registry_rejects_multiple_configured_primaries_for_one_authority_key() -> None:
    first = StaticEventProvider("first", ())
    second = StaticEventProvider("second", ())

    with pytest.raises(ValueError, match="configured primary"):
        ProviderRegistry(
            (
                _registration("First", first, tier=ProviderTier.PRIMARY),
                _registration("Second", second, tier=ProviderTier.PRIMARY),
            )
        )


def test_registry_allows_disjoint_country_primary_authority() -> None:
    japan = StaticEventProvider("japan-primary", ())
    vietnam = StaticEventProvider("vietnam-primary", ())
    japan_registration = _registration(
        "Japan primary", japan, tier=ProviderTier.PRIMARY
    )
    vietnam_registration = _registration(
        "Vietnam primary", vietnam, tier=ProviderTier.PRIMARY
    )
    vietnam_registration = replace(
        vietnam_registration,
        capabilities=replace(
            vietnam_registration.capabilities,
            country_codes=frozenset({"VNM"}),
        ),
    )

    registry = ProviderRegistry((japan_registration, vietnam_registration))

    assert len(registry.registrations) == 2


def test_selection_uses_explicit_tier_precedence_not_registration_order() -> None:
    secondary = StaticEventProvider("secondary", ())
    primary = StaticEventProvider("primary", ())
    registry = ProviderRegistry(
        (
            _registration("Secondary", secondary, tier=ProviderTier.SECONDARY),
            _registration("Primary", primary, tier=ProviderTier.PRIMARY),
        )
    )

    selection = registry.select(_query(), ProviderRole.EVENT_DISCOVERY)

    assert [item.name for item in selection.registrations] == ["Primary", "Secondary"]


@pytest.mark.asyncio
async def test_composite_propagates_tiers_and_primary_wins_canonical_selection() -> (
    None
):
    primary = StaticEventProvider("primary", (_event("primary", magnitude=4.0),))
    secondary = StaticEventProvider("secondary", (_event("secondary", magnitude=7.0),))
    registry = ProviderRegistry(
        (
            _registration("Secondary", secondary, tier=ProviderTier.SECONDARY),
            _registration("Primary", primary, tier=ProviderTier.PRIMARY),
        )
    )

    batch = await CompositeDisasterEventProvider(registry).find_recent_events(
        _query(), now=NOW
    )
    identity = DefaultEventPolicy().identify(batch.records).physical_events[0]

    assert {item.provider_tier for item in batch.records} == {
        ProviderTier.PRIMARY,
        ProviderTier.SECONDARY,
    }
    assert identity.event.source.source_id == "primary"
    assert identity.event.measurement(MeasurementKind.MAGNITUDE) is not None
    assert (
        identity.event.measurement(MeasurementKind.MAGNITUDE).source.source_id
        == "primary"
    )
    assert {item.source.source_id for item in identity.observations} == {
        "primary",
        "secondary",
    }
    assert {item.source.source_id for item in identity.event.measurements} == {
        "primary",
        "secondary",
    }


def test_secondary_only_observation_is_a_valid_fallback() -> None:
    secondary = _event("secondary")
    resolution = DefaultEventPolicy().resolve(
        (replace(secondary, provider_tier=ProviderTier.SECONDARY),),
        _query(),
        now=NOW,
    )

    assert resolution.selected is not None
    assert resolution.selected.source.source_id == "secondary"


def test_primary_metadata_wins_conflict_and_secondary_is_retained() -> None:
    primary = replace(
        _event("primary", location="Primary location", magnitude=4.0),
        provider_tier=ProviderTier.PRIMARY,
    )
    secondary = replace(
        _event("secondary", location="Conflicting location", magnitude=7.0),
        provider_tier=ProviderTier.SECONDARY,
    )
    secondary = replace(secondary, event_id="secondary:event")
    identity = DefaultEventPolicy().identify((secondary, primary)).physical_events[0]

    assert identity.event.event_id == "flood:shared"
    assert identity.event.location == "Primary location"
    assert identity.event.source.source_id == "primary"
    assert identity.event.measurement(MeasurementKind.MAGNITUDE).value == 4.0
    assert {
        item.value for item in identity.event.measurements_of(MeasurementKind.MAGNITUDE)
    } == {
        4.0,
        7.0,
    }
    assert len(identity.observations) == 2


def test_canonical_selection_is_order_independent() -> None:
    primary = replace(
        _event("primary", magnitude=4.0), provider_tier=ProviderTier.PRIMARY
    )
    secondary = replace(
        _event(
            "secondary",
            magnitude=7.0,
            event_time=NOW - timedelta(minutes=30),
        ),
        provider_tier=ProviderTier.SECONDARY,
    )
    policy = DefaultEventPolicy()

    forward = policy.identify((primary, secondary)).physical_events[0]
    reverse = policy.identify((secondary, primary)).physical_events[0]

    assert forward.event == reverse.event
    assert forward.physical_event_id == reverse.physical_event_id


@pytest.mark.asyncio
async def test_gfm_is_the_sole_primary_flood_event_discovery_authority() -> None:
    service = build_current_disaster_report(Settings())
    try:
        registry = service._provider_registry  # noqa: SLF001
        primary = [
            item
            for item in registry.select(
                _query(), ProviderRole.EVENT_DISCOVERY
            ).registrations
            if item.tier is ProviderTier.PRIMARY
        ]
        assert [(item.name, item.source_id) for item in primary] == [
            ("CEMS Global Flood Monitoring (GFM)", "cems-gfm-floods")
        ]
    finally:
        await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("disaster", "provider_name", "source_id"),
    (
        (Disaster.WILDFIRE, "NASA EONET Wildfires", "nasa-eonet-wildfires"),
        (Disaster.LANDSLIDE, "NASA COOLR Landslides", "nasa-coolr-landslides"),
    ),
)
async def test_nasa_catalog_is_the_sole_primary_authority(
    disaster: Disaster, provider_name: str, source_id: str
) -> None:
    service = build_current_disaster_report(Settings())
    try:
        registry = service._provider_registry  # noqa: SLF001
        primary = [
            item
            for item in registry.registrations
            if item.tier is ProviderTier.PRIMARY
            and disaster in item.capabilities.disasters
            and ProviderRole.EVENT_DISCOVERY in item.capabilities.roles
        ]
        assert [(item.name, item.source_id) for item in primary] == [
            (provider_name, source_id)
        ]
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_smithsonian_is_the_sole_primary_volcanic_event_authority() -> None:
    service = build_current_disaster_report(Settings())
    try:
        registry = service._provider_registry  # noqa: SLF001
        primary = [
            item
            for item in registry.registrations
            if item.tier is ProviderTier.PRIMARY
            and Disaster.VOLCANIC_ERUPTION in item.capabilities.disasters
            and item.capabilities.roles == frozenset({ProviderRole.EVENT_DISCOVERY})
        ]
        assert [(item.name, item.source_id) for item in primary] == [
            (
                "Smithsonian / USGS Weekly Volcanic Activity Report",
                "smithsonian-usgs-volcanic-activity",
            )
        ]
        registration = primary[0]
        assert registration.capabilities.country_codes is None
        assert registration.capabilities.event_scopes == frozenset(
            {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
        )
        assert registration.allowed_hosts == frozenset(
            {"volcano.si.edu", "webservices.volcano.si.edu"}
        )
    finally:
        await service.aclose()
