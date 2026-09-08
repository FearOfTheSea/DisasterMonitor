from datetime import UTC, datetime, timedelta

from disaster_monitor.application.disaster import (
    GeographicScope,
    ProviderBatch,
    WorldwideDisasterEvent,
)
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService as ActiveIncidentsServiceType,
)
from disaster_monitor.application.sources.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    IncidentActivityStatus,
    IncidentWatch,
    IncidentWatchScope,
    ProviderTier,
    SourceAuthority,
    SourceReference,
    descriptive_event_geometry,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 20, 6, tzinfo=UTC)


class FakeWorldwideProvider:
    def __init__(
        self,
        source_id: str,
        result: ProviderBatch[WorldwideDisasterEvent] | Exception,
    ) -> None:
        self.source_id = source_id
        self.allowed_hosts = frozenset({f"{source_id}.example"})
        self.result = result
        self.queries = []

    async def find_worldwide_events(self, query, *, now):
        self.queries.append((query, now))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _source(
    source_id: str,
    event_time: datetime,
    *,
    authority: SourceAuthority = SourceAuthority.SCIENTIFIC_AUTHORITY,
) -> SourceReference:
    return SourceReference(
        source_id=source_id,
        publisher=f"{source_id} publisher",
        title=f"{source_id} bulletin",
        canonical_url=f"https://{source_id}.example/events",
        published_at=event_time,
        updated_at=event_time + timedelta(minutes=5),
        retrieved_at=NOW,
        authority=authority,
    )


def _event(
    source_id: str,
    disaster: Disaster,
    event_id: str,
    event_time: datetime,
    *,
    descriptive: bool = False,
    latitude: float = 32.5,
    longitude: float = 133.5,
    location: str | None = None,
    activity_status: IncidentActivityStatus = IncidentActivityStatus.UNKNOWN,
) -> WorldwideDisasterEvent:
    source = _source(source_id, event_time)
    geometry = (
        descriptive_event_geometry("Provider supplied location text", source)
        if descriptive
        else point_event_geometry(latitude, longitude, source)
    )
    return WorldwideDisasterEvent(
        event_id=event_id,
        disaster=disaster,
        location=location or f"{disaster.value} location",
        event_time=event_time,
        source=source,
        geometry=geometry,
        provider_ids=(f"{source_id}:{event_id}",),
        activity_status=activity_status,
    )


def _registration(
    name: str,
    provider: FakeWorldwideProvider,
    disaster: Disaster,
    *,
    tier: ProviderTier = ProviderTier.SECONDARY,
    configured: bool = True,
) -> ProviderRegistration:
    return ProviderRegistration(
        name,
        provider,
        ProviderCapabilities(
            roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
            disasters=frozenset({disaster}),
            country_codes=None,
            requires_configuration=not configured,
            geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
            event_scopes=frozenset({GeographicScope.WORLDWIDE}),
        ),
        tier=tier,
        source_id=provider.source_id,
        configured=configured,
        allowed_hosts=provider.allowed_hosts,
        worldwide_provider=provider,
    )


def _coverage(snapshot):
    return {item.disaster: item for item in snapshot.coverage}


def _active_incidents_service(
    provider_registry: ProviderRegistry, **kwargs
) -> ActiveIncidentsServiceType:
    return ActiveIncidentsServiceType(
        provider_registry,
        country_catalog=StaticCountryCatalog(),
        **kwargs,
    )


def _watch(disaster: Disaster) -> IncidentWatch:
    return IncidentWatch(
        watch_id=f"incident-watch:{disaster.value}",
        disaster=disaster,
        scope=IncidentWatchScope.worldwide(),
        enabled=True,
        refresh_interval_seconds=900,
        created_at=NOW,
        updated_at=NOW,
        next_refresh_at=NOW,
    )
