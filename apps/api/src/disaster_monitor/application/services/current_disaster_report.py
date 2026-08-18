"""Compatibility facade over the shared bounded disaster tool workflow."""

from collections.abc import Callable, Iterable
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
    AgentTool,
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
from disaster_monitor.application.services.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
)


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


class _InjectedProviderIdentity:
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self.allowed_hosts = frozenset[str]()


class CurrentDisasterReportService:
    """Preserve the legacy API while executing the shared allowlisted tools."""

    def __init__(
        self,
        event_provider: DisasterEventProvider,
        situation_report_provider: SituationReportProvider,
        *,
        provider_registry: ProviderRegistry | None = None,
        provider_capabilities: tuple[ProviderCapabilities, ProviderCapabilities]
        | None = None,
        event_policies: EventPolicyRegistry | None = None,
        evidence_reconciler: EvidenceReconciler | None = None,
        renderer: DisasterReportRenderer | None = None,
        clock: Callable[[], datetime] = _now_utc,
        source_catalog: SourceCatalog | None = None,
        operational_evidence: OperationalEvidenceRecorder | None = None,
    ) -> None:
        self._event_provider = event_provider
        self._situation_report_provider = situation_report_provider
        if provider_registry is not None:
            self._provider_registry = provider_registry
        elif provider_capabilities is not None:
            self._provider_registry = _compatibility_registry(
                event_provider, situation_report_provider, provider_capabilities
            )
        else:
            raise ValueError(
                "Direct provider injection requires explicit provider capabilities."
            )
        self._event_policies = event_policies or default_event_policy_registry()
        self._evidence_reconciler = evidence_reconciler or EvidenceReconciler()
        self._renderer = renderer or DisasterReportRenderer()
        self._clock = clock
        self._source_catalog = source_catalog or _EmptySourceCatalog()
        self._operational_evidence = operational_evidence
        self._agent_tools = self.build_agent_tools(self._source_catalog)

    @property
    def provider_registry(self) -> ProviderRegistry:
        return self._provider_registry

    @property
    def source_catalog(self) -> SourceCatalog:
        return self._source_catalog

    def build_agent_tools(
        self,
        source_catalog: SourceCatalog,
        additional_tools: Iterable[AgentTool] = (),
    ) -> ToolRegistry:
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
                operational_evidence=self._operational_evidence,
            ),
            additional_tools,
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
    capabilities: tuple[ProviderCapabilities, ProviderCapabilities],
) -> ProviderRegistry:
    return ProviderRegistry(
        (
            ProviderRegistration(
                "Injected event provider",
                _InjectedProviderIdentity("injected-event-provider"),
                capabilities[0],
                event_provider=event_provider,
            ),
            ProviderRegistration(
                "Injected situation provider",
                _InjectedProviderIdentity("injected-situation-provider"),
                capabilities[1],
                situation_provider=situation_provider,
            ),
        )
    )
