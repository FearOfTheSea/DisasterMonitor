from datetime import UTC, datetime, timedelta

from disaster_monitor.application.evidence.inspection import (
    EvidenceTimelineEventType,
    build_evidence_timeline,
    evidence_timeline_entry,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    SourceAuthority,
    SourceReference,
    descriptive_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
SOURCE = SourceReference(
    "fixture-source",
    "Fixture authority",
    "Fixture event",
    "https://example.test/event",
    NOW,
    NOW,
    NOW,
    SourceAuthority.SCIENTIFIC_AUTHORITY,
)
COUNTRY = StaticCountryCatalog().get_by_alpha3("JPN")
assert COUNTRY is not None
EVENT = DisasterEvent(
    "fixture:event",
    Disaster.EARTHQUAKE,
    "Ishikawa, Japan",
    COUNTRY,
    NOW - timedelta(hours=1),
    SOURCE,
    geometry=descriptive_event_geometry("Fixture location", SOURCE),
)


def test_timeline_merges_typed_additions_in_time_order_and_deduplicates_ids() -> None:
    additions = (
        evidence_timeline_entry(
            event_type=EvidenceTimelineEventType.WATCH_CHANGE,
            occurred_at=NOW - timedelta(minutes=5),
            title="Watch refreshed",
            detail="The operator watch was refreshed.",
            related_id="watch-1",
        ),
        evidence_timeline_entry(
            event_type=EvidenceTimelineEventType.IMAGERY_SELECTION,
            occurred_at=NOW - timedelta(minutes=10),
            title="Imagery selected",
            detail="The selected scene passed the evidence gate.",
            related_id="scene-1",
        ),
        evidence_timeline_entry(
            event_type=EvidenceTimelineEventType.WATCH_CHANGE,
            occurred_at=NOW - timedelta(minutes=5),
            title="Watch refreshed",
            detail="The operator watch was refreshed.",
            related_id="watch-1",
        ),
    )

    timeline = build_evidence_timeline(EVENT, (), None, additional=additions)

    assert len(timeline) == 3
    assert [item.event_type for item in timeline] == [
        EvidenceTimelineEventType.NORMALIZED_OBSERVATION,
        EvidenceTimelineEventType.IMAGERY_SELECTION,
        EvidenceTimelineEventType.WATCH_CHANGE,
    ]


def test_coverage_warning_is_not_mislabeled_as_warning_lifecycle() -> None:
    timeline = build_evidence_timeline(
        EVENT,
        (),
        None,
        warnings=("One provider timed out.",),
        retrieved_at=NOW,
    )

    assert timeline[-1].event_type is EvidenceTimelineEventType.COVERAGE_STATUS
    assert all(
        item.event_type is not EvidenceTimelineEventType.WARNING_LIFECYCLE
        for item in timeline
    )
