from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ground_imagery.select_observations import (
    SelectionReason,
    select_observations,
)
from disaster_monitor.application.ground_imagery.temporal_policy import (
    ImpactOnset,
    build_temporal_plan,
)
from disaster_monitor.domain.disaster import Disaster, IncidentActivityStatus
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationQuality,
    ObservationReadiness,
    QualityState,
    Sensor,
)
from disaster_monitor.domain.imagery.regions import polygon_from_geojson


def _footprint():
    return polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
        }
    )


def _observation(
    product_id: str,
    sensor: Sensor,
    captured_at: datetime,
    *,
    usable: float,
    mode: str | None = None,
    orbit: int | None = None,
    direction: str | None = None,
    polarizations: tuple[str, ...] = (),
    recipe: str | None = None,
) -> Observation:
    return Observation(
        observation_id=product_id,
        sensor=sensor,
        identity=AcquisitionIdentity(
            product_id=product_id,
            provider="cdse",
            acquisition_id=product_id,
            platform="sentinel",
        ),
        capture=CaptureInterval(captured_at, captured_at + timedelta(minutes=5)),
        footprint=_footprint(),
        readiness=ObservationReadiness.RENDERABLE,
        quality=ObservationQuality(
            covered_fraction=1,
            usable_fraction=usable,
            obscured_fraction=1 - usable,
            uncertain_fraction=0,
            uncovered_fraction=0,
            component_usable_fractions=(("whole", usable),),
            quality_state=QualityState.USEFUL
            if usable >= 0.8
            else QualityState.OBSCURED,
            mask_definition="fixture-v1",
        ),
        mode=mode,
        relative_orbit=orbit,
        orbit_direction=direction,
        polarizations=polarizations,
        recipe_version=recipe,
    )


def test_latest_prefers_newest_useful_scene_over_newer_cloudy_scene() -> None:
    onset = ImpactOnset.exact(datetime(2024, 5, 5, tzinfo=UTC), source_id="event")
    plan = build_temporal_plan(
        onset=onset,
        reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        disaster=Disaster.FLOOD,
        activity_status=IncidentActivityStatus.ONGOING,
    )
    cloudy = _observation(
        "s2-cloudy",
        Sensor.SENTINEL_2,
        datetime(2024, 5, 19, tzinfo=UTC),
        usable=0.4,
    )
    clear = _observation(
        "s2-clear",
        Sensor.SENTINEL_2,
        datetime(2024, 5, 18, tzinfo=UTC),
        usable=0.95,
    )

    result = select_observations(
        plan,
        {Sensor.SENTINEL_2: (cloudy, clear)},
    )

    latest = result.for_sensor(Sensor.SENTINEL_2).for_role("latest_useful")
    assert latest.observation is clear
    assert latest.reason is SelectionReason.SELECTED


def test_sensors_select_independently_when_one_has_no_usable_result() -> None:
    onset = ImpactOnset.exact(datetime(2024, 5, 5, tzinfo=UTC), source_id="event")
    plan = build_temporal_plan(
        onset=onset,
        reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        disaster=Disaster.FLOOD,
        activity_status=IncidentActivityStatus.ONGOING,
    )
    radar = _observation(
        "s1-useful",
        Sensor.SENTINEL_1,
        datetime(2024, 5, 19, tzinfo=UTC),
        usable=0.9,
        mode="IW",
        orbit=24,
        direction="descending",
        polarizations=("VV", "VH"),
        recipe="gamma0-terrain-v1",
    )
    result = select_observations(
        plan,
        {
            Sensor.SENTINEL_1: (radar,),
            Sensor.SENTINEL_2: (),
        },
    )

    assert result.for_sensor(Sensor.SENTINEL_1).has_observation
    assert not result.for_sensor(Sensor.SENTINEL_2).has_observation
    assert result.for_sensor(Sensor.SENTINEL_2).partial_failure_reason in {
        SelectionReason.NO_ACQUISITION,
        SelectionReason.NO_RECENT_OBSERVATION,
    }


def test_radar_baseline_requires_compatible_orbit_and_recipe() -> None:
    onset = ImpactOnset.exact(datetime(2024, 5, 10, tzinfo=UTC), source_id="event")
    plan = build_temporal_plan(
        onset=onset,
        reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        disaster=Disaster.EARTHQUAKE,
        activity_status=IncidentActivityStatus.ENDED,
    )
    after = _observation(
        "s1-after",
        Sensor.SENTINEL_1,
        datetime(2024, 5, 12, tzinfo=UTC),
        usable=0.9,
        mode="IW",
        orbit=24,
        direction="descending",
        polarizations=("VV", "VH"),
        recipe="gamma0-terrain-v1",
    )
    opposite = _observation(
        "s1-before-opposite",
        Sensor.SENTINEL_1,
        datetime(2024, 5, 8, tzinfo=UTC),
        usable=0.95,
        mode="IW",
        orbit=25,
        direction="ascending",
        polarizations=("VV", "VH"),
        recipe="gamma0-terrain-v1",
    )
    result = select_observations(plan, {Sensor.SENTINEL_1: (after, opposite)})

    baseline = result.for_sensor(Sensor.SENTINEL_1).for_role("pre_event_reference")
    assert baseline.observation is None
    assert baseline.reason is SelectionReason.NO_COMPARABLE_BASELINE
