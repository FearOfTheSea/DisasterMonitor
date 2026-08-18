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
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
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
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.application.use_cases.run_disaster_agent import RunDisasterAgent
from disaster_monitor.domain.disaster import (
    Country,
    GeographicArea,
    Hazard,
    SituationReport,
    SourceReference,
)
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
                    hazard=query.hazard,
                ),
            )
        )


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
        hazard=Hazard.FLOOD,
        location="Pacific basin",
        event_time=NOW,
        source=source,
        latitude=1.0,
        longitude=2.0,
    )


def _registry(provider: object) -> ProviderRegistry:
    return ProviderRegistry(
        (
            ProviderRegistration(
                "Synthetic worldwide floods",
                provider,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    hazards=frozenset({Hazard.FLOOD}),
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
async def test_synthetic_worldwide_hazard_uses_the_neutral_agent_path() -> None:
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

    assert provider.queries == [WorldwideDisasterQuery(Hazard.FLOOD)]
    assert answer.selected_event is not None
    assert answer.selected_event.hazard is Hazard.FLOOD
    assert answer.investigation is not None
    assert answer.investigation.geographic_scope == "worldwide"
    assert answer.investigation.hazard == "flood"


@pytest.mark.asyncio
async def test_worldwide_runtime_translates_report_status_and_capabilities() -> None:
    provider = SyntheticWorldwideProvider(_event())
    report_service = WorldwideDisasterReportService(
        _registry(provider), clock=lambda: NOW
    )
    report = await report_service.execute(WorldwideDisasterQuery(Hazard.FLOOD))
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
                    hazards=frozenset({Hazard.FLOOD}),
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
        WorldwideDisasterQuery(Hazard.FLOOD)
    )

    assert not report.partial
    assert report.capability_gaps == ()
    assert report.termination_reason == "completed_worldwide_evidence"


def test_country_codes_none_does_not_authorize_worldwide_queries() -> None:
    capabilities = ProviderCapabilities(
        roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
        hazards=frozenset({Hazard.FLOOD}),
        country_codes=None,
    )
    country = Country("THA", "Thailand", (), GeographicArea(-1, 1, -1, 1))
    assert capabilities.supports(
        DisasterQuery(Hazard.FLOOD, country, "recent", ("latest",)),
        ProviderRole.EVENT_DISCOVERY,
    )
    assert not capabilities.supports(
        WorldwideDisasterQuery(Hazard.FLOOD), ProviderRole.EVENT_DISCOVERY
    )


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
    assert task.worldwide_query == WorldwideDisasterQuery(Hazard.FLOOD)
