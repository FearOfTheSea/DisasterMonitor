from datetime import UTC, datetime, timedelta

from disaster_monitor.application.agent.investigation_cases import (
    CrossHazardAssessmentStatus,
    assess_cross_hazard_pair,
)
from disaster_monitor.application.services.active_incidents import ActiveIncident
from disaster_monitor.domain.disaster import (
    Disaster,
    ProviderTier,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)


def _incident(
    disaster: Disaster,
    event_id: str,
    *,
    event_time: datetime,
    longitude: float,
) -> ActiveIncident:
    source = SourceReference(
        f"fixture-{event_id}",
        "Fixture authority",
        "Fixture event",
        f"https://example.test/{event_id}",
        event_time,
        event_time,
        event_time,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    return ActiveIncident(
        event_id=event_id,
        disaster=disaster,
        location="Fixture location",
        event_time=event_time,
        geometry=point_event_geometry(35, longitude, source),
        measurements=(),
        provider_ids=("fixture",),
        provider_tier=ProviderTier.SECONDARY,
        source_authority=source.authority,
        source=source,
    )


def test_investigation_evaluation_only_labels_supported_proximity_as_association() -> (
    None
):
    now = datetime(2026, 8, 5, tzinfo=UTC)
    assessment, correlations = assess_cross_hazard_pair(
        _incident(Disaster.EARTHQUAKE, "quake", event_time=now, longitude=139),
        _incident(
            Disaster.LANDSLIDE,
            "slide",
            event_time=now + timedelta(hours=1),
            longitude=139.2,
        ),
        causation_requested=True,
    )

    assert assessment.status is CrossHazardAssessmentStatus.ASSOCIATED
    assert len(correlations) == 1
    assert "does not establish causation" in assessment.limitation
