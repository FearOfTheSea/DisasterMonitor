from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.agent.models import AgentStatus
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    validate_disaster_task,
)
from disaster_monitor.application.agent.tooling import ToolRegistry
from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
    WorldwideSelectionIntent,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_evidence_policy import (
    validate_worldwide_event_evidence,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.application.use_cases.run_disaster_agent import RunDisasterAgent
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
    EventMeasurement,
    GeographicArea,
    MeasurementKind,
    ProviderTier,
    SituationReport,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.composition import build_current_disaster_report
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)


class SyntheticWorldwideProvider:
    source_id = "synthetic-floods"
    allowed_hosts = frozenset({"floods.example"})

    def __init__(self, event: WorldwideDisasterEvent) -> None:
        self.event = event
        self.queries: list[WorldwideDisasterQuery] = []

    async def find_worldwide_events(self, query, *, now):
        self.queries.append(query)
        return ProviderBatch((self.event,))

    async def find_recent_events(self, query, *, now):
        return ProviderBatch()

    async def get_worldwide_situation_reports(self, event, query, *, now):
        return ProviderBatch(
            (
                SituationReport(
                    source=event.source,
                    narrative="Worldwide flood situation evidence.",
                    disaster=query.disaster,
                ),
            )
        )


class TieredWorldwideProvider:
    def __init__(
        self,
        source_id: str,
        result: ProviderBatch[WorldwideDisasterEvent] | Exception,
    ) -> None:
        self.source_id = source_id
        self.allowed_hosts = frozenset({f"{source_id}.example"})
        self.result = result

    async def find_worldwide_events(self, query, *, now):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class NoGeneralModel:
    async def generate(self, request):
        raise AssertionError("worldwide disaster requests must stay source-backed")


def _event() -> WorldwideDisasterEvent:
    source = SourceReference(
        source_id="synthetic-floods",
        publisher="Synthetic Flood Authority",
        title="Worldwide flood bulletin",
        canonical_url="https://floods.example/events/flood-1",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
    )
    return WorldwideDisasterEvent(
        event_id="flood-1",
        disaster=Disaster.FLOOD,
        location="Pacific basin",
        event_time=NOW,
        source=source,
        geometry=point_event_geometry(1.0, 2.0, source),
    )


def _tiered_event(
    source_id: str,
    event_id: str,
    event_time: datetime,
    *,
    disaster: Disaster = Disaster.FLOOD,
    magnitude: float | None = None,
) -> WorldwideDisasterEvent:
    source = SourceReference(
        source_id=source_id,
        publisher=f"{source_id} publisher",
        title=f"{source_id} event",
        canonical_url=f"https://{source_id}.example/{event_id}",
        published_at=event_time,
        updated_at=event_time,
        retrieved_at=NOW,
    )
    measurements = (
        (EventMeasurement(MeasurementKind.MAGNITUDE, magnitude, source=source),)
        if magnitude is not None
        else ()
    )
    return WorldwideDisasterEvent(
        event_id=event_id,
        disaster=disaster,
        location=f"{source_id} location",
        event_time=event_time,
        source=source,
        geometry=point_event_geometry(1.0, 2.0, source),
        measurements=measurements,
    )


def _tiered_registration(
    name: str,
    provider: TieredWorldwideProvider,
    *,
    disaster: Disaster,
    tier: ProviderTier,
) -> ProviderRegistration:
    return ProviderRegistration(
        name,
        provider,
        ProviderCapabilities(
            roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
            disasters=frozenset({disaster}),
            country_codes=None,
            geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
            event_scopes=frozenset({GeographicScope.WORLDWIDE}),
        ),
        tier=tier,
        source_id=provider.source_id,
        allowed_hosts=provider.allowed_hosts,
        worldwide_provider=provider,
    )


def _tiered_service(
    registrations: tuple[ProviderRegistration, ...],
) -> WorldwideDisasterReportService:
    return WorldwideDisasterReportService(
        ProviderRegistry(registrations),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_worldwide_default_policy_keeps_primary_over_newer_secondary() -> None:
    primary = TieredWorldwideProvider(
        "primary-floods",
        ProviderBatch((_tiered_event("primary-floods", "old", NOW),)),
    )
    secondary = TieredWorldwideProvider(
        "secondary-floods",
        ProviderBatch(
            (_tiered_event("secondary-floods", "new", NOW.replace(hour=13)),)
        ),
    )

    report = await _tiered_service(
        (
            _tiered_registration(
                "Secondary floods",
                secondary,
                disaster=Disaster.FLOOD,
                tier=ProviderTier.SECONDARY,
            ),
            _tiered_registration(
                "Primary floods",
                primary,
                disaster=Disaster.FLOOD,
                tier=ProviderTier.PRIMARY,
            ),
        )
    ).execute(WorldwideDisasterQuery(Disaster.FLOOD))

    assert report.selected_event is not None
    assert report.selected_event.event_id == "old"
    assert report.selected_event.source.source_id == "primary-floods"


@pytest.mark.asyncio
async def test_worldwide_earthquake_strongest_intent_stays_with_primary_tier() -> None:
    primary = TieredWorldwideProvider(
        "primary-quakes",
        ProviderBatch(
            (
                _tiered_event(
                    "primary-quakes",
                    "primary",
                    NOW,
                    disaster=Disaster.EARTHQUAKE,
                    magnitude=4.0,
                ),
            )
        ),
    )
    secondary = TieredWorldwideProvider(
        "secondary-quakes",
        ProviderBatch(
            (
                _tiered_event(
                    "secondary-quakes",
                    "secondary",
                    NOW,
                    disaster=Disaster.EARTHQUAKE,
                    magnitude=8.0,
                ),
            )
        ),
    )

    report = await _tiered_service(
        (
            _tiered_registration(
                "Secondary quakes",
                secondary,
                disaster=Disaster.EARTHQUAKE,
                tier=ProviderTier.SECONDARY,
            ),
            _tiered_registration(
                "Primary quakes",
                primary,
                disaster=Disaster.EARTHQUAKE,
                tier=ProviderTier.PRIMARY,
            ),
        )
    ).execute(
        WorldwideDisasterQuery(
            Disaster.EARTHQUAKE,
            selection_intent=WorldwideSelectionIntent.STRONGEST,
        )
    )

    assert report.selected_event is not None
    assert report.selected_event.event_id == "primary"


@pytest.mark.asyncio
async def test_worldwide_secondary_is_fallback_after_failed_or_rejected_primary() -> (
    None
):
    rejected_primary = TieredWorldwideProvider(
        "rejected-primary",
        ProviderBatch(
            records=(_tiered_event("spoofed-source", "bad", NOW),),
            issues=(
                ProviderIssue(
                    "Rejected primary",
                    "Rejected primary reported malformed data.",
                    reason_code="invalid_record",
                ),
            ),
        ),
    )
    secondary = TieredWorldwideProvider(
        "secondary-fallback",
        ProviderBatch((_tiered_event("secondary-fallback", "fallback", NOW),)),
    )
    rejected_registration = _tiered_registration(
        "Rejected primary",
        rejected_primary,
        disaster=Disaster.FLOOD,
        tier=ProviderTier.PRIMARY,
    )
    secondary_registration = _tiered_registration(
        "Secondary fallback",
        secondary,
        disaster=Disaster.FLOOD,
        tier=ProviderTier.SECONDARY,
    )

    report = await _tiered_service(
        (secondary_registration, rejected_registration)
    ).execute(WorldwideDisasterQuery(Disaster.FLOOD))

    assert report.selected_event is not None
    assert report.selected_event.event_id == "fallback"
    assert any(
        "Rejected primary reported malformed data" in warning
        for warning in report.warnings
    )
    assert any("violated source policy" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_worldwide_secondary_falls_back_after_typed_primary_failure() -> None:
    primary = TieredWorldwideProvider("failed-primary", RuntimeError("offline"))
    secondary = TieredWorldwideProvider(
        "secondary-after-failure",
        ProviderBatch((_tiered_event("secondary-after-failure", "fallback", NOW),)),
    )

    report = await _tiered_service(
        (
            _tiered_registration(
                "Failed primary",
                primary,
                disaster=Disaster.FLOOD,
                tier=ProviderTier.PRIMARY,
            ),
            _tiered_registration(
                "Secondary after failure",
                secondary,
                disaster=Disaster.FLOOD,
                tier=ProviderTier.SECONDARY,
            ),
        )
    ).execute(WorldwideDisasterQuery(Disaster.FLOOD))

    assert report.selected_event is not None
    assert report.selected_event.event_id == "fallback"
    assert any(
        "Failed primary could not be reached" in warning for warning in report.warnings
    )


@pytest.mark.asyncio
async def test_worldwide_tier_selection_is_independent_of_registration_order() -> None:
    async def run(order: tuple[str, ...]) -> str | None:
        providers = {
            "primary": TieredWorldwideProvider(
                "ordered-primary",
                ProviderBatch((_tiered_event("ordered-primary", "primary", NOW),)),
            ),
            "secondary": TieredWorldwideProvider(
                "ordered-secondary",
                ProviderBatch(
                    (
                        _tiered_event(
                            "ordered-secondary", "secondary", NOW.replace(hour=13)
                        ),
                    )
                ),
            ),
        }
        registrations = tuple(
            _tiered_registration(
                f"{label.title()} ordered",
                providers[label],
                disaster=Disaster.FLOOD,
                tier=ProviderTier.PRIMARY
                if label == "primary"
                else ProviderTier.SECONDARY,
            )
            for label in order
        )
        report = await _tiered_service(registrations).execute(
            WorldwideDisasterQuery(Disaster.FLOOD)
        )
        return report.selected_event.event_id if report.selected_event else None

    assert await run(("primary", "secondary")) == await run(("secondary", "primary"))


def _registry(provider: object) -> ProviderRegistry:
    return ProviderRegistry(
        (
            ProviderRegistration(
                "Synthetic worldwide floods",
                provider,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.FLOOD}),
                    country_codes=None,
                    geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
                    event_scopes=frozenset({GeographicScope.WORLDWIDE}),
                ),
                source_id="synthetic-floods",
                allowed_hosts=frozenset({"floods.example"}),
                event_provider=provider,
                worldwide_provider=provider,
            ),
        )
    )


@pytest.mark.asyncio
async def test_synthetic_worldwide_disaster_uses_the_neutral_agent_path() -> None:
    provider = SyntheticWorldwideProvider(_event())
    registry = _registry(provider)
    report_service = WorldwideDisasterReportService(registry, clock=lambda: NOW)
    catalog = StaticCountryCatalog()
    runtime = DisasterAgentRuntime(
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
        tool_registry=ToolRegistry(()),
        worldwide_report=report_service,
    )

    answer = await RunDisasterAgent(runtime, NoGeneralModel()).execute(
        "Any flood news worldwide?", conversation_id="test-session"
    )

    assert provider.queries == [WorldwideDisasterQuery(Disaster.FLOOD)]
    assert answer.selected_event is not None
    assert answer.selected_event.disaster is Disaster.FLOOD
    assert answer.selected_event.geography_status.value == "worldwide"
    assert answer.investigation is not None
    assert answer.investigation.geographic_scope == "worldwide"
    assert answer.investigation.disaster == "flood"


@pytest.mark.asyncio
async def test_worldwide_runtime_translates_report_status_and_capabilities() -> None:
    provider = SyntheticWorldwideProvider(_event())
    report_service = WorldwideDisasterReportService(
        _registry(provider), clock=lambda: NOW
    )
    report = await report_service.execute(WorldwideDisasterQuery(Disaster.FLOOD))
    result = replace(
        report,
        partial=False,
        capability_gaps=("Synthetic capability gap",),
        investigation_actions=("Synthetic investigation action",),
        termination_reason="synthetic_completed",
    )

    class ReportResult:
        async def execute(self, query):
            return result

    catalog = StaticCountryCatalog()
    runtime = DisasterAgentRuntime(
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
        tool_registry=ToolRegistry(()),
        worldwide_report=ReportResult(),  # type: ignore[arg-type]
    )

    state = await runtime.run("Any flood news worldwide?")

    assert state.final_status is AgentStatus.COMPLETED
    assert state.capability_gaps == ["Synthetic capability gap"]
    assert [action.description for action in state.actions] == [
        "Synthetic investigation action"
    ]
    assert state.termination_reason == "synthetic_completed"


@pytest.mark.asyncio
async def test_worldwide_completeness_changes_when_situation_capability_executes() -> (
    None
):
    provider = SyntheticWorldwideProvider(_event())
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "Synthetic worldwide floods with situation evidence",
                provider,
                ProviderCapabilities(
                    roles=frozenset(
                        {
                            ProviderRole.EVENT_DISCOVERY,
                            ProviderRole.SITUATION_EVIDENCE,
                        }
                    ),
                    disasters=frozenset({Disaster.FLOOD}),
                    country_codes=None,
                    geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
                    event_scopes=frozenset({GeographicScope.WORLDWIDE}),
                    situation_scopes=frozenset({GeographicScope.WORLDWIDE}),
                ),
                source_id="synthetic-floods",
                allowed_hosts=frozenset({"floods.example"}),
                worldwide_provider=provider,
                worldwide_situation_provider=provider,
            ),
        )
    )
    report = await WorldwideDisasterReportService(registry, clock=lambda: NOW).execute(
        WorldwideDisasterQuery(Disaster.FLOOD)
    )

    assert not report.partial
    assert report.capability_gaps == ()
    assert report.termination_reason == "completed_worldwide_evidence"


def test_country_codes_none_does_not_authorize_worldwide_queries() -> None:
    capabilities = ProviderCapabilities(
        roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
        disasters=frozenset({Disaster.FLOOD}),
        country_codes=None,
    )
    country = Country("THA", "Thailand", (), GeographicArea(-1, 1, -1, 1))
    assert capabilities.supports(
        DisasterQuery(Disaster.FLOOD, country, "recent", ("latest",)),
        ProviderRole.EVENT_DISCOVERY,
    )
    assert not capabilities.supports(
        WorldwideDisasterQuery(Disaster.FLOOD), ProviderRole.EVENT_DISCOVERY
    )


def test_worldwide_area_geometry_is_accepted_without_a_fabricated_point() -> None:
    point = _event()
    geometry = EventGeometry(
        kind=EventGeometryKind.AREA,
        source=point.source,
        coordinates=(
            EventCoordinate(10.0, 20.0),
            EventCoordinate(11.0, 21.0),
            EventCoordinate(10.5, 22.0),
        ),
    )
    area_event = replace(point, geometry=geometry)

    accepted = validate_worldwide_event_evidence(
        area_event,
        WorldwideDisasterQuery(Disaster.FLOOD),
        source_id="synthetic-floods",
        allowed_hosts=frozenset({"floods.example"}),
    )

    assert accepted.geometry is geometry
    assert accepted.geometry.coordinates == geometry.coordinates


def test_worldwide_task_scope_is_explicit_before_provider_selection() -> None:
    catalog = StaticCountryCatalog()
    query_parser = DisasterQueryParser(catalog)
    question = "Any flood news worldwide?"
    task = validate_disaster_task(
        question,
        deterministic_task_draft(question),
        country_catalog=catalog,
        query_parser=query_parser,
    )
    assert task.geographic_scope is GeographicScope.WORLDWIDE
    assert task.country is None
    assert task.query is None
    assert task.worldwide_query == WorldwideDisasterQuery(Disaster.FLOOD)


@pytest.mark.asyncio
async def test_gfm_worldwide_capability_is_explicitly_bounded() -> None:
    service = build_current_disaster_report(Settings())
    try:
        selection = service._provider_registry.select(  # noqa: SLF001
            WorldwideDisasterQuery(Disaster.FLOOD, time_window_days=365, limit=999),
            ProviderRole.EVENT_DISCOVERY,
        )
        assert [item.name for item in selection.registrations] == [
            "CEMS Global Flood Monitoring (GFM)"
        ]
        assert selection.registrations[0].tier.value == "primary"
        assert selection.registrations[0].capabilities.event_scopes == frozenset(
            {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
        )
    finally:
        await service.aclose()
