"""Source selection, event discovery, and situation-evidence tools."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InformationNeed,
    SourceInformationRole,
    SourceSelectionSummary,
)
from disaster_monitor.application.agent.tools import ToolDescription
from disaster_monitor.application.disaster import ProviderBatch
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.application.services.event_resolution import EventPolicyRegistry
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)


@dataclass(frozen=True, slots=True)
class SourceToolDependencies:
    provider_registry: ProviderRegistry
    source_catalog: SourceCatalog
    event_provider: DisasterEventProvider
    situation_provider: SituationReportProvider
    event_policies: EventPolicyRegistry
    clock: Callable[[], datetime]


class _BaseTool:
    def __init__(self, dependencies: SourceToolDependencies) -> None:
        self.dependencies = dependencies

    def now(self) -> datetime:
        value = self.dependencies.clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ListSourcesForTaskTool(_BaseTool):
    description = ToolDescription(
        "list_sources_for_task",
        "Match maintained source intelligence to the validated disaster, country, "
        "and roles.",
        ("validated_task",),
        (),
        ("source_selection",),
        tuple(role.value for role in SourceInformationRole),
        False,
    )

    async def execute(self, state: AgentExecutionState) -> str:
        task = state.task
        if task.query is None or task.disaster is None or task.country is None:
            raise ValueError("Source selection requires a canonical disaster query.")
        configured: list[str] = []
        unconfigured: list[str] = []
        for registration in self.dependencies.provider_registry.registrations:
            if not registration.source_id:
                continue
            if any(
                registration.capabilities.supports(task.query, role)
                for role in ProviderRole
            ):
                (configured if registration.configured else unconfigured).append(
                    registration.source_id
                )
        requested_roles = _requested_source_roles(task.information_needs)
        catalog_matches = {
            source.source_id
            for source in self.dependencies.source_catalog.sources()
            if task.disaster in source.supported_disasters
            and (
                source.country_codes is None
                or task.country.alpha3_code in source.country_codes
            )
        }
        unsupported_roles = tuple(
            role.value
            for role in requested_roles
            if not any(
                role in source.information_roles
                for source in self.dependencies.source_catalog.sources()
                if source.source_id in catalog_matches
            )
        )
        satisfied_by_admitted_assets = (
            {
                SourceInformationRole.IMAGERY.value,
                SourceInformationRole.MAP_LAYERS.value,
            }
            if state.workspace.multimodal_assets
            else set()
        )
        unsupported = tuple(
            role
            for role in unsupported_roles
            if role not in satisfied_by_admitted_assets
        )
        executable_ids = set(configured) | set(unconfigured)
        known_not_executable = tuple(sorted(catalog_matches - executable_ids))
        supplementary = tuple(
            source.source_id
            for source in self.dependencies.source_catalog.sources()
            if source.source_id in catalog_matches
            and SourceInformationRole.HUMANITARIAN_REPORTING in source.information_roles
        )
        gaps = []
        event_selection = self.dependencies.provider_registry.select(
            task.query, ProviderRole.EVENT_DISCOVERY
        )
        if not event_selection.registrations:
            gaps.append("No event-discovery source is executable for this task.")
        for role in unsupported:
            gaps.append(f"No maintained executable source supports role {role}.")
        state.workspace.source_selection = SourceSelectionSummary(
            configured_source_ids=tuple(configured),
            unconfigured_source_ids=tuple(unconfigured),
            known_not_executable_source_ids=known_not_executable,
            supplementary_source_ids=supplementary,
            unsupported_roles=unsupported,
            coverage_gaps=tuple(gaps),
        )
        state.workspace.source_ids.extend(configured)
        state.capability_gaps.extend(gaps)
        return (
            f"Selected {len(configured)} configured source registrations; "
            f"{len(unconfigured)} suitable registrations require configuration."
        )


class FindDisasterEventTool(_BaseTool):
    description = ToolDescription(
        "find_disaster_event",
        "Query capability-selected event providers and resolve one physical event.",
        ("validated_task", "source_selection"),
        (),
        ("event_batch", "selected_event", "alternatives"),
        (SourceInformationRole.EVENT_DISCOVERY.value,),
        True,
    )

    async def execute(self, state: AgentExecutionState) -> str:
        task = state.task
        if task.query is None:
            raise ValueError("Event discovery requires a canonical disaster query.")
        selection = self.dependencies.provider_registry.select(
            task.query, ProviderRole.EVENT_DISCOVERY
        )
        if not selection.registrations:
            state.capability_gaps.append(
                "No event-discovery provider supports this disaster and country."
            )
            return "No event-discovery provider is available for the validated task."
        try:
            batch = await self.dependencies.event_provider.find_recent_events(
                task.query, now=self.now()
            )
            state.workspace.event_batch = _as_batch(batch)
        except Exception:
            state.workspace.event_batch = ProviderBatch()
            state.warnings.append(
                f"A {task.query.disaster.value} event source could not be reached or "
                "returned invalid data."
            )
        state.warnings.extend(
            issue.message for issue in state.workspace.event_batch.issues
        )
        policy = self.dependencies.event_policies.for_disaster(task.query.disaster)
        resolution = policy.resolve(
            state.workspace.event_batch.records,
            task.query,
            now=self.now(),
        )
        state.workspace.physical_events = resolution.physical_events
        state.workspace.selected_physical_event = resolution.selected_physical_event
        state.workspace.selected_event = resolution.selected
        state.workspace.alternatives = resolution.alternatives
        if resolution.selected is None:
            return "No matching event was discovered from the selected sources."
        return f"Selected the source-backed event {resolution.selected.event_id}."


class RetrieveSituationEvidenceTool(_BaseTool):
    description = ToolDescription(
        "retrieve_situation_evidence",
        "Retrieve normalized event-correlated official and supplementary reports.",
        ("selected_event",),
        (),
        ("situation_reports", "provider_issues"),
        (),
        True,
    )

    def supported_information_roles(
        self, state: AgentExecutionState
    ) -> tuple[str, ...]:
        query = state.task.query
        if query is None:
            return ()
        selection = self.dependencies.provider_registry.select(
            query, ProviderRole.SITUATION_EVIDENCE
        )
        source_ids = {
            registration.source_id
            for registration in selection.registrations
            if registration.source_id
        }
        roles = {
            role.value
            for source in self.dependencies.source_catalog.sources()
            if source.source_id in source_ids
            for role in source.information_roles
        }
        requested = set(_requested_source_roles(state.task.information_needs))
        return tuple(sorted(roles & requested))

    async def execute(self, state: AgentExecutionState) -> str:
        event = state.workspace.selected_event
        query = state.task.query
        if event is None or query is None:
            raise ValueError("Situation evidence requires a selected event.")
        selection = self.dependencies.provider_registry.select(
            query, ProviderRole.SITUATION_EVIDENCE, event=event
        )
        state.warnings.extend(
            f"{name} is unavailable because required configuration is missing."
            for name in selection.unavailable_configuration
        )
        if not selection.registrations:
            state.workspace.situation_batch = ProviderBatch()
            state.capability_gaps.append(
                "No configured situation-evidence provider supports the selected event."
            )
            return (
                "No situation-evidence provider is executable for the selected event."
            )
        try:
            batch = await self.dependencies.situation_provider.get_situation_reports(
                event, query, now=self.now()
            )
            state.workspace.situation_batch = _as_batch(batch)
        except Exception:
            state.workspace.situation_batch = ProviderBatch()
            state.warnings.append(
                "The situation-report source could not be reached or returned "
                "invalid data."
            )
        state.warnings.extend(
            issue.message for issue in state.workspace.situation_batch.issues
        )
        return (
            f"Retrieved {len(state.workspace.situation_batch.records)} "
            "situation reports."
        )


def _requested_source_roles(
    needs: tuple[InformationNeed, ...],
) -> tuple[SourceInformationRole, ...]:
    roles = [SourceInformationRole.EVENT_DISCOVERY]
    mapping = {
        InformationNeed.FATALITIES: SourceInformationRole.CASUALTY_REPORTING,
        InformationNeed.INJURIES: SourceInformationRole.CASUALTY_REPORTING,
        InformationNeed.MISSING_PERSONS: SourceInformationRole.CASUALTY_REPORTING,
        InformationNeed.PHYSICAL_DAMAGE: SourceInformationRole.PHYSICAL_DAMAGE,
        InformationNeed.INFRASTRUCTURE_DISRUPTION: (
            SourceInformationRole.INFRASTRUCTURE_STATUS
        ),
        InformationNeed.WARNINGS: SourceInformationRole.OFFICIAL_WARNING,
        InformationNeed.EMERGENCY_RESPONSE: SourceInformationRole.EMERGENCY_RESPONSE,
        InformationNeed.IMAGES: SourceInformationRole.IMAGERY,
        InformationNeed.MAP_VISUALIZATION: SourceInformationRole.MAP_LAYERS,
    }
    roles.extend(mapping[item] for item in needs if item in mapping)
    return tuple(dict.fromkeys(roles))


def _as_batch[T](value: ProviderBatch[T] | tuple[T, ...]) -> ProviderBatch[T]:
    return value if isinstance(value, ProviderBatch) else ProviderBatch(tuple(value))
