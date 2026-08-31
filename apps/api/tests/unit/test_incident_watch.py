from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.services.incident_change_detection import (
    IncidentChangeDetector,
)
from disaster_monitor.application.use_cases.manage_incident_watches import (
    InvalidIncidentWatchScopeError,
    ManageIncidentWatches,
)
from disaster_monitor.application.use_cases.refresh_incident_watch import (
    IncidentWatchRefreshRetryableError,
    RefreshIncidentWatch,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    EventMeasurement,
    IncidentChangeKind,
    IncidentWatch,
    IncidentWatchObservation,
    IncidentWatchScope,
    MeasurementKind,
    ProviderTier,
    SourceAuthority,
    SourceReference,
    WatchCoverageState,
    WatchIncident,
    WatchScopeKind,
    point_event_geometry,
    watch_incident_document,
    watch_incident_from_document,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

NOW = datetime(2026, 8, 31, 8, tzinfo=UTC)


def source(
    source_id: str = "fixture-earthquakes",
    *,
    updated_at: datetime | None = NOW,
) -> SourceReference:
    return SourceReference(
        source_id=source_id,
        publisher="Fixture Scientific Authority",
        title="Fixture earthquake record",
        canonical_url=f"https://{source_id}.example/events/quake-1",
        published_at=NOW - timedelta(minutes=10),
        updated_at=updated_at,
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        snapshot_id=f"snapshot:{source_id}",
    )


def incident(
    *,
    event_id: str = "quake-1",
    magnitude: float = 5.2,
    latitude: float = 10.5,
    source_records: tuple[SourceReference, ...] | None = None,
    provider_ids: tuple[str, ...] = ("fixture:quake-1",),
) -> WatchIncident:
    primary = source()
    return WatchIncident.from_source_evidence(
        event_id=event_id,
        disaster=Disaster.EARTHQUAKE,
        location="Fixture coast",
        event_time=NOW - timedelta(minutes=15),
        geometry=point_event_geometry(latitude, 20.25, primary),
        measurements=(
            EventMeasurement(
                MeasurementKind.MAGNITUDE,
                magnitude,
                source=primary,
            ),
        ),
        provider_ids=provider_ids,
        provider_tier=ProviderTier.SECONDARY,
        source_authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        source=primary,
        evidence_sources=source_records or (primary,),
    )


def watch(*, scope: IncidentWatchScope | None = None) -> IncidentWatch:
    return IncidentWatch(
        watch_id="incident-watch:test",
        disaster=Disaster.EARTHQUAKE,
        scope=scope or IncidentWatchScope.worldwide(),
        enabled=True,
        refresh_interval_seconds=900,
        created_at=NOW,
        updated_at=NOW,
        next_refresh_at=NOW,
    )


def observation(
    *incidents: WatchIncident,
    coverage: WatchCoverageState = WatchCoverageState.EVENTS_FOUND,
    observed_at: datetime = NOW,
    successful: bool = True,
    retryable: bool = False,
) -> IncidentWatchObservation:
    return IncidentWatchObservation.create(
        watch_id="incident-watch:test",
        observed_at=observed_at,
        coverage_state=coverage,
        incidents=incidents,
        provider_names=("Fixture provider",),
        warnings=(),
        successful=successful,
        retryable=retryable,
    )


def test_watch_requires_exactly_one_canonical_scope_and_bounded_interval() -> None:
    assert IncidentWatchScope.worldwide().kind is WatchScopeKind.WORLDWIDE
    assert IncidentWatchScope.country("VNM", "Vietnam").country_name == "Vietnam"

    with pytest.raises(ValueError, match="Worldwide"):
        IncidentWatchScope(WatchScopeKind.WORLDWIDE, "VNM", "Vietnam")
    with pytest.raises(ValueError, match="canonical country"):
        IncidentWatchScope(WatchScopeKind.COUNTRY)
    with pytest.raises(ValueError, match="between 300 and 86400"):
        IncidentWatch(
            watch_id="incident-watch:invalid",
            disaster=Disaster.FLOOD,
            scope=IncidentWatchScope.worldwide(),
            enabled=True,
            refresh_interval_seconds=60,
            created_at=NOW,
            updated_at=NOW,
            next_refresh_at=NOW,
        )


@pytest.mark.asyncio
async def test_manage_watch_canonicalizes_country_and_rejects_ambiguous_scope() -> None:
    repository = InMemoryOperationalRepository()
    use_case = ManageIncidentWatches(
        repository,
        StaticCountryCatalog(),
        clock=lambda: NOW,
        identifier=lambda: "fixed",
    )

    created = await use_case.create(
        disaster=Disaster.FLOOD,
        scope_kind=WatchScopeKind.COUNTRY,
        country="vietnam",
        refresh_interval_seconds=1800,
    )

    assert created.watch_id == "incident-watch:fixed"
    assert created.scope == IncidentWatchScope.country("VNM", "Vietnam")
    assert created.next_refresh_at == NOW
    with pytest.raises(InvalidIncidentWatchScopeError):
        await use_case.create(
            disaster=Disaster.FLOOD,
            scope_kind=WatchScopeKind.WORLDWIDE,
            country="Vietnam",
            refresh_interval_seconds=1800,
        )
    with pytest.raises(InvalidIncidentWatchScopeError):
        await use_case.create(
            disaster=Disaster.FLOOD,
            scope_kind=WatchScopeKind.COUNTRY,
            country="Vietnam and Japan",
            refresh_interval_seconds=1800,
        )


def test_change_detection_classifies_typed_source_backed_changes() -> None:
    detector = IncidentChangeDetector()
    baseline_incident = incident()
    baseline = observation(baseline_incident, observed_at=NOW)
    additional_source = source("corroborating-catalog")
    changed = observation(
        incident(
            magnitude=5.6,
            latitude=11.0,
            source_records=(source(), additional_source),
        ),
        observed_at=NOW + timedelta(minutes=15),
    )

    changes = detector.detect(
        watch=watch(),
        previous=baseline,
        previous_successful=baseline,
        current=changed,
    )

    assert {item.kind for item in changes} == {
        IncidentChangeKind.MEASUREMENTS_CHANGED,
        IncidentChangeKind.GEOMETRY_CHANGED,
        IncidentChangeKind.EVIDENCE_SET_CHANGED,
    }
    assert all(item.source_ids for item in changes)
    assert all(item.before_hash and item.after_hash for item in changes)


def test_watch_incident_document_round_trip_preserves_each_evidence_source() -> None:
    primary = source()
    geometry_source = source("fixture-geometry")
    measurement_source = source("fixture-measurement")
    value = WatchIncident.from_source_evidence(
        event_id="quake-1",
        disaster=Disaster.EARTHQUAKE,
        location="Fixture coast",
        event_time=NOW,
        geometry=point_event_geometry(10.5, 20.25, geometry_source),
        measurements=(
            EventMeasurement(
                MeasurementKind.MAGNITUDE,
                5.2,
                source=measurement_source,
            ),
        ),
        provider_ids=("fixture:quake-1",),
        provider_tier=ProviderTier.SECONDARY,
        source_authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        source=primary,
        evidence_sources=(primary, geometry_source, measurement_source),
    )

    restored = watch_incident_from_document(watch_incident_document(value))

    assert restored == value
    assert restored.geometry is not None
    assert restored.geometry.source.source_id == "fixture-geometry"
    assert restored.measurements[0].source.source_id == "fixture-measurement"


def test_new_event_gap_and_coverage_transitions_are_deterministic() -> None:
    detector = IncidentChangeDetector()
    baseline = observation(incident(), observed_at=NOW)
    empty = observation(
        coverage=WatchCoverageState.NO_MATCHING_RECORDS,
        observed_at=NOW + timedelta(minutes=15),
    )

    gap_changes = detector.detect(
        watch=watch(),
        previous=baseline,
        previous_successful=baseline,
        current=empty,
    )

    assert [item.kind for item in gap_changes] == [
        IncidentChangeKind.COVERAGE_CHANGED,
        IncidentChangeKind.OBSERVATION_GAP,
    ]
    assert "not evidence that the disaster ended" in gap_changes[1].detail

    unavailable = observation(
        coverage=WatchCoverageState.UNAVAILABLE,
        observed_at=NOW + timedelta(minutes=30),
        successful=False,
        retryable=True,
    )
    unavailable_changes = detector.detect(
        watch=watch(),
        previous=baseline,
        previous_successful=baseline,
        current=unavailable,
    )
    assert [item.kind for item in unavailable_changes] == [
        IncidentChangeKind.COVERAGE_CHANGED
    ]

    initial = detector.detect(
        watch=watch(),
        previous=None,
        previous_successful=None,
        current=baseline,
    )
    assert [item.kind for item in initial] == [IncidentChangeKind.NEW_EVENT]

    repeated_empty = observation(
        coverage=WatchCoverageState.NO_MATCHING_RECORDS,
        observed_at=NOW + timedelta(hours=1),
    )
    repeated_transition = detector.detect(
        watch=watch(),
        previous=baseline,
        previous_successful=baseline,
        current=repeated_empty,
    )
    assert repeated_transition[0].change_id != gap_changes[0].change_id


@pytest.mark.asyncio
async def test_refresh_is_idempotent_and_marks_only_meaningful_changes_unread() -> None:
    repository = InMemoryOperationalRepository()
    await repository.create_watch(watch())
    result = observation(incident())

    class Discovery:
        calls = 0

        async def observe_watch(self, selected_watch: IncidentWatch):
            self.calls += 1
            assert selected_watch.watch_id == watch().watch_id
            return result

    use_case = RefreshIncidentWatch(repository, Discovery())

    first = await use_case.execute(watch().watch_id)
    second = await use_case.execute(watch().watch_id)

    assert len(first.changes) == 1
    assert first.changes[0].kind is IncidentChangeKind.NEW_EVENT
    assert second.changes == ()
    stored = await repository.get_watch(watch().watch_id)
    assert stored is not None and stored.unread_change_count == 1
    assert len(await repository.watch_changes(watch().watch_id)) == 1
    assert len(repository.watch_observations) == 1


@pytest.mark.asyncio
async def test_retryable_refresh_persists_degradation_before_worker_retry() -> None:
    repository = InMemoryOperationalRepository()
    await repository.create_watch(watch())
    degraded = observation(
        coverage=WatchCoverageState.DEGRADED,
        successful=False,
        retryable=True,
    )

    class Discovery:
        async def observe_watch(self, selected_watch: IncidentWatch):
            del selected_watch
            return degraded

    with pytest.raises(IncidentWatchRefreshRetryableError):
        await RefreshIncidentWatch(repository, Discovery()).execute(watch().watch_id)

    stored = await repository.get_watch(watch().watch_id)
    assert stored is not None
    assert stored.coverage_state is WatchCoverageState.DEGRADED
    assert stored.last_checked_at == NOW
