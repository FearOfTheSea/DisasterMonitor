"""Compatibility facade over the shared bounded disaster tool workflow."""

from collections.abc import Callable
from datetime import UTC, datetime

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InformationNeed,
    OutputModality,
    SourceDescriptor,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.agent.planning import default_investigation_plan
from disaster_monitor.application.agent.tooling import (
    DisasterToolDependencies,
    ToolRegistry,
    build_disaster_tool_registry,
    execute_plan,
)
from disaster_monitor.application.disaster import DisasterQuery, DisasterReport
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.application.services.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.services.event_resolution import (
    EventPolicyRegistry,
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.domain.disaster import Hazard


def _now_utc() -> datetime:
    return datetime.now(UTC)


class _EmptySourceCatalog:
    """Compatibility metadata view used only by directly constructed test facades."""

    @property
    def version(self) -> str:
        return "compatibility-empty"

    def sources(self) -> tuple[SourceDescriptor, ...]:
        return ()

    def get(self, source_id: str) -> SourceDescriptor | None:
        return None


class CurrentDisasterReportService:
    """Preserve the legacy API while executing the shared allowlisted tools."""

    def __init__(
        self,
        event_provider: DisasterEventProvider,
        situation_report_provider: SituationReportProvider,
        *,
        provider_registry: ProviderRegistry | None = None,
        event_policies: EventPolicyRegistry | None = None,
        evidence_reconciler: EvidenceReconciler | None = None,
        renderer: DisasterReportRenderer | None = None,
        clock: Callable[[], datetime] = _now_utc,
        source_catalog: SourceCatalog | None = None,
    ) -> None:
        self._event_provider = event_provider
        self._situation_report_provider = situation_report_provider
        self._provider_registry = provider_registry or _compatibility_registry(
            event_provider, situation_report_provider
        )
        self._event_policies = event_policies or default_event_policy_registry()
        self._evidence_reconciler = evidence_reconciler or EvidenceReconciler()
        self._renderer = renderer or DisasterReportRenderer()
        self._clock = clock
        self._source_catalog = source_catalog or _EmptySourceCatalog()
        self._agent_tools = self.build_agent_tools(self._source_catalog)

    def build_agent_tools(self, source_catalog: SourceCatalog) -> ToolRegistry:
        """Expose this facade's exact dependencies through bounded agent tools."""
        return build_disaster_tool_registry(
            DisasterToolDependencies(
                self._provider_registry,
                source_catalog,
                self._event_provider,
                self._situation_report_provider,
                self._event_policies,
                self._evidence_reconciler,
                self._renderer,
                self._clock,
            )
        )

    async def execute(self, query: DisasterQuery) -> DisasterReport:
        task = ValidatedDisasterTask(
            question=(
                f"Current {query.hazard.value} information in "
                f"{query.country.canonical_name}"
            ),
            kind=TaskKind.INVESTIGATION,
            requires_evidence=True,
            hazard=query.hazard,
            country=query.country,
            date_from=query.date_from,
            date_to=query.date_to,
            information_needs=(InformationNeed.EVENT_OVERVIEW,),
            output_modalities=(OutputModality.TEXT,),
            query=query,
        )
        plan = default_investigation_plan(task)
        state = AgentExecutionState(task, plan)
        state.capability_gaps.extend(plan.capability_gaps)
        await execute_plan(state, self._agent_tools)
        if state.workspace.report is None:
            raise RuntimeError("The shared disaster tool workflow produced no report.")
        return state.workspace.report

    async def aclose(self) -> None:
        """Close live provider clients when the application shuts down."""
        close = getattr(self._event_provider, "aclose", None)
        if close is not None:
            await close()
        close = getattr(self._situation_report_provider, "aclose", None)
        if close is not None:
            await close()


def _compatibility_registry(
    event_provider: DisasterEventProvider,
    situation_provider: SituationReportProvider,
) -> ProviderRegistry:
    return ProviderRegistry(
        (
            ProviderRegistration(
                "Injected event provider",
                event_provider,
                ProviderCapabilities(
                    frozenset({ProviderRole.EVENT_DISCOVERY}),
                    frozenset(Hazard),
                    None,
                ),
            ),
            ProviderRegistration(
                "Injected situation provider",
                situation_provider,
                ProviderCapabilities(
                    frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    frozenset(Hazard),
                    None,
                ),
            ),
        )
    )
