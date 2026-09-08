"""Map admitted discovery records to the Active Incidents read model."""

from itertools import groupby

from disaster_monitor.application.disaster import (
    ObservationKind,
    WorldwideDisasterEvent,
)
from disaster_monitor.application.evidence.event_identity import event_observation_key
from disaster_monitor.application.evidence.event_resolution import EventPolicyRegistry
from disaster_monitor.application.incidents.country_association import (
    CountryAssociationBasis,
    IncidentCountryAssociation,
    IncidentCountryResolver,
)
from disaster_monitor.application.incidents.models import ActiveIncident
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    EventGeographyStatus,
    PhysicalEventIdentity,
    ProviderTier,
    SourceReference,
)


def incident(
    event: WorldwideDisasterEvent,
    provider_tier: ProviderTier,
    country_resolver: IncidentCountryResolver,
) -> ActiveIncident:
    country = (
        None
        if event.observation_kind is ObservationKind.ACQUISITION
        else country_resolver.resolve(event)
    )
    return ActiveIncident(
        event_id=event.event_id,
        disaster=event.disaster,
        country=country,
        location=event.location,
        event_time=event.event_time,
        geometry=event.geometry,
        measurements=event.measurements,
        provider_ids=event.provider_ids,
        lineage_ids=event.lineage_ids,
        provider_tier=provider_tier,
        source_authority=event.source.authority,
        source=event.source,
        evidence_sources=(event.source,),
        observation_kind=event.observation_kind,
        activity_status=event.activity_status,
    )


def country_incident(identity: PhysicalEventIdentity) -> ActiveIncident:
    event = identity.event
    return ActiveIncident(
        event_id=event.event_id,
        disaster=event.disaster,
        country=IncidentCountryAssociation(
            country_code=event.country.alpha3_code,
            country_name=event.country.canonical_name,
            basis=(
                CountryAssociationBasis.SOURCE_MENTION
                if event.geography_status
                is EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
                else CountryAssociationBasis.COORDINATE_POLYGON
            ),
        ),
        location=event.location,
        event_time=event.event_time,
        geometry=event.geometry,
        measurements=event.measurements,
        provider_ids=event.provider_ids,
        lineage_ids=event.lineage_ids,
        provider_tier=event.provider_tier,
        source_authority=event.source.authority,
        source=event.source,
        physical_event_id=identity.physical_event_id,
        evidence_sources=_evidence_sources(identity),
        observation_kind=event.observation_kind,
        activity_status=event.activity_status,
    )


def country_observation(event: DisasterEvent) -> ActiveIncident:
    """Keep country-scoped product acquisitions visible outside incident counts."""
    return ActiveIncident(
        event_id=event.event_id,
        disaster=event.disaster,
        country=IncidentCountryAssociation(
            country_code=event.country.alpha3_code,
            country_name=event.country.canonical_name,
            basis=CountryAssociationBasis.SOURCE_MENTION,
        ),
        location=event.location,
        event_time=event.event_time,
        geometry=event.geometry,
        measurements=event.measurements,
        provider_ids=event.provider_ids,
        lineage_ids=event.lineage_ids,
        provider_tier=event.provider_tier,
        source_authority=event.source.authority,
        source=event.source,
        evidence_sources=(event.source,),
        observation_kind=event.observation_kind,
        activity_status=event.activity_status,
    )


def resolve_worldwide_incidents(
    incidents: tuple[ActiveIncident, ...],
    *,
    country_catalog: CountryCatalog,
    event_policies: EventPolicyRegistry,
) -> tuple[ActiveIncident, ...]:
    """Resolve all admitted worldwide observations through hazard-owned policies."""
    normalized: list[DisasterEvent] = []
    active_by_observation: dict[str, ActiveIncident] = {}
    countryless: list[ActiveIncident] = []
    for item in incidents:
        if item.country is None:
            countryless.append(item)
            continue
        country = country_catalog.get_by_alpha3(item.country.country_code)
        if country is None:
            countryless.append(item)
            continue
        event = DisasterEvent(
            event_id=item.event_id,
            disaster=item.disaster,
            location=item.location,
            country=country,
            event_time=item.event_time,
            source=item.source,
            geometry=item.geometry,
            measurements=item.measurements,
            provider_ids=item.provider_ids,
            lineage_ids=item.lineage_ids,
            geography_status=(
                EventGeographyStatus.IN_COUNTRY
                if item.country.basis is CountryAssociationBasis.COORDINATE_POLYGON
                else EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
            ),
            provider_tier=item.provider_tier,
            observation_kind=item.observation_kind,
            activity_status=item.activity_status,
        )
        normalized.append(event)
        active_by_observation[event_observation_key(event)] = item

    resolved: list[ActiveIncident] = [*countryless]
    ordered = sorted(
        normalized,
        key=lambda event: (
            event.disaster.value,
            event.country.alpha3_code,
            event_observation_key(event),
        ),
    )
    for _, group_iterator in groupby(
        ordered,
        key=lambda event: (event.disaster, event.country.alpha3_code),
    ):
        group = tuple(group_iterator)
        policy = event_policies.for_disaster(group[0].disaster)
        for identity in policy.identify(group).physical_events:
            representative = active_by_observation.get(
                event_observation_key(identity.event)
            )
            if representative is None:
                representative = active_by_observation[
                    event_observation_key(identity.observations[0])
                ]
            resolved.append(resolved_worldwide_incident(identity, representative))
    return tuple(resolved)


def resolved_worldwide_incident(
    identity: PhysicalEventIdentity,
    representative: ActiveIncident,
) -> ActiveIncident:
    event = identity.event
    associated = representative.country
    if associated is None:
        raise ValueError("A resolved country-scoped incident requires an association.")
    return ActiveIncident(
        event_id=event.event_id,
        disaster=event.disaster,
        country=associated,
        location=event.location,
        event_time=event.event_time,
        geometry=event.geometry,
        measurements=event.measurements,
        provider_ids=event.provider_ids,
        lineage_ids=event.lineage_ids,
        provider_tier=event.provider_tier,
        source_authority=event.source.authority,
        source=event.source,
        physical_event_id=identity.physical_event_id,
        evidence_sources=_evidence_sources(identity),
        observation_kind=event.observation_kind,
        activity_status=event.activity_status,
    )


def _evidence_sources(identity: PhysicalEventIdentity) -> tuple[SourceReference, ...]:
    return tuple(
        sorted(
            {item.source for item in identity.observations},
            key=lambda item: (item.source_id, item.canonical_url),
        )
    )
