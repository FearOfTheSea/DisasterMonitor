from datetime import UTC, date, datetime, timedelta

from disaster_monitor.application.ground_imagery.temporal_policy import (
    AgeClass,
    ImpactOnset,
    build_temporal_plan,
    classify_capture,
    classify_freshness,
    watch_check_interval,
)
from disaster_monitor.domain.disaster import Disaster, IncidentActivityStatus
from disaster_monitor.domain.imagery.observations import (
    CaptureInterval,
    TemporalRole,
)


def test_exact_onset_separates_same_day_captures() -> None:
    onset = ImpactOnset.exact(datetime(2024, 5, 5, 12, tzinfo=UTC), source_id="usgs:1")
    before = CaptureInterval(
        datetime(2024, 5, 5, 11, tzinfo=UTC), datetime(2024, 5, 5, 11, 30, tzinfo=UTC)
    )
    after = CaptureInterval(
        datetime(2024, 5, 5, 12, tzinfo=UTC), datetime(2024, 5, 5, 12, 5, tzinfo=UTC)
    )

    assert classify_capture(before, onset) == "definitely_pre_event"
    assert classify_capture(after, onset) == "definitely_after_onset"


def test_date_only_unknown_timezone_widens_onset_interval() -> None:
    onset = ImpactOnset.from_date(date(2024, 5, 5), source_id="report:1")

    assert onset.precision == "date_only_unknown_timezone"
    assert onset.earliest < datetime(2024, 5, 5, tzinfo=UTC)
    assert onset.latest > datetime(2024, 5, 6, tzinfo=UTC)


def test_unknown_onset_uses_observation_labels_not_before_after() -> None:
    reference = datetime(2024, 5, 20, 12, tzinfo=UTC)
    plan = build_temporal_plan(
        onset=None,
        reference_time=reference,
        disaster=Disaster.FLOOD,
        activity_status=IncidentActivityStatus.UNKNOWN,
    )

    assert plan.onset is None
    assert plan.window_for(TemporalRole.LATEST_USEFUL).start == reference - timedelta(
        days=14
    )
    assert plan.window_for(TemporalRole.EARLIER_REFERENCE).end == reference - timedelta(
        days=14
    )
    assert plan.label_for(TemporalRole.LATEST_USEFUL) == "Latest observation"
    assert plan.label_for(TemporalRole.EARLIER_REFERENCE) == "Earlier observation"


def test_known_onset_latest_window_never_starts_before_onset() -> None:
    onset = ImpactOnset.exact(datetime(2024, 5, 18, tzinfo=UTC), source_id="event:1")
    plan = build_temporal_plan(
        onset=onset,
        reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        disaster=Disaster.WILDFIRE,
        activity_status=IncidentActivityStatus.ONGOING,
    )

    assert plan.window_for(TemporalRole.LATEST_USEFUL).start == onset.latest
    assert plan.window_for(TemporalRole.FIRST_USEFUL_AFTER_ONSET).end <= datetime(
        2024, 5, 20, tzinfo=UTC
    )


def test_freshness_is_based_on_capture_end_and_hazard_class() -> None:
    reference = datetime(2024, 5, 10, 12, tzinfo=UTC)
    capture = CaptureInterval(
        reference - timedelta(hours=50), reference - timedelta(hours=49)
    )

    assert classify_freshness(capture, reference, Disaster.FLOOD) == AgeClass.AGING
    assert (
        classify_freshness(capture, reference, Disaster.EARTHQUAKE) == AgeClass.RECENT
    )


def test_watch_schedule_changes_by_lifecycle_period() -> None:
    created = datetime(2024, 5, 1, tzinfo=UTC)

    assert watch_check_interval(
        created, created + timedelta(hours=2), False
    ) == timedelta(hours=1)
    assert watch_check_interval(
        created, created + timedelta(days=10), False
    ) == timedelta(hours=3)
    assert watch_check_interval(
        created, created + timedelta(days=20), False
    ) == timedelta(hours=12)
    assert watch_check_interval(
        created, created + timedelta(days=20), True
    ) == timedelta(hours=24)
    assert watch_check_interval(created, created + timedelta(days=31), True) is None
