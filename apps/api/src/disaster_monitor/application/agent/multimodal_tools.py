"""Bounded agent tools over already-admitted multimodal artifacts."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    SourceInformationRole,
)
from disaster_monitor.application.agent.tooling import AgentTool, ToolDescription
from disaster_monitor.application.services.common_operational_picture import (
    CommonOperationalPictureBuilder,
)
from disaster_monitor.application.services.coordination_handoffs import (
    CoordinationHandoffPlanner,
)
from disaster_monitor.application.services.multimodal_association import (
    MultimodalEventAssociator,
)
from disaster_monitor.application.services.multimodal_state import (
    build_multimodal_evidence_state,
)
from disaster_monitor.application.services.visual_analysis import VisualAnalysisService
from disaster_monitor.domain.multimodal import EventAssociationStatus, VisualObservation


@dataclass(frozen=True, slots=True)
class MultimodalToolDependencies:
    associator: MultimodalEventAssociator
    visual_analysis: VisualAnalysisService
    cop_builder: CommonOperationalPictureBuilder
    clock: Callable[[], datetime]
    handoff_planner: CoordinationHandoffPlanner = field(
        default_factory=CoordinationHandoffPlanner
    )


def build_multimodal_agent_tools(
    dependencies: MultimodalToolDependencies,
) -> tuple[AgentTool, ...]:
    return (
        AnalyzeMultimodalAssetsTool(dependencies),
        BuildCommonOperationalPictureTool(dependencies),
    )


class AnalyzeMultimodalAssetsTool:
    description = ToolDescription(
        "analyze_multimodal_assets",
        "Associate already-admitted image assets to the selected physical event and "
        "produce typed analytical observations.",
        ("selected_event", "evidence_world_state", "admitted_multimodal_assets"),
        (),
        ("asset_event_associations", "visual_observations", "multimodal_state"),
        (SourceInformationRole.IMAGERY.value,),
        False,
    )

    def __init__(self, dependencies: MultimodalToolDependencies) -> None:
        self._dependencies = dependencies

    async def execute(self, state: AgentExecutionState) -> str:
        physical_event = state.workspace.selected_physical_event
        evidence_state = state.workspace.evidence_state
        assets = state.workspace.multimodal_assets
        if physical_event is None or evidence_state is None:
            raise ValueError(
                "Multimodal analysis requires selected physical-event and EW state."
            )
        if not assets:
            state.capability_gaps.append(
                "No admitted multimodal asset is available for analysis."
            )
            return "No admitted multimodal assets were available."
        associations = tuple(
            self._dependencies.associator.associate(asset, physical_event)
            for asset in assets
        )
        observations: list[VisualObservation] = []
        for asset, association in zip(assets, associations, strict=True):
            if association.status != EventAssociationStatus.ASSOCIATED:
                continue
            try:
                produced = await self._dependencies.visual_analysis.analyze(
                    asset,
                    association,
                    question=state.task.question,
                )
                state.visual_model_call_count += 1
                observations.extend(produced)
            except Exception:
                state.visual_model_call_count += 1
                state.warnings.append(
                    "A local visual analysis was unavailable or returned invalid data; "
                    "the text evidence path remains available."
                )
        now = self._now()
        state.workspace.multimodal_associations = associations
        state.workspace.visual_observations = tuple(observations)
        state.workspace.multimodal_state = build_multimodal_evidence_state(
            evidence_state,
            assets,
            associations,
            tuple(observations),
            evaluated_at=now,
        )
        try:
            multimodal_handoff = (
                self._dependencies.handoff_planner.for_multimodal_state(
                    state.workspace.multimodal_state
                )
            )
            state.workspace.specialist_handoffs = (
                *state.workspace.specialist_handoffs,
                multimodal_handoff,
            )
        except ValueError:
            state.capability_gaps.append(
                "Typed multimodal handoff failed its ownership or provenance gate; "
                "the single-supervisor path remains active."
            )
        associated_count = sum(
            item.status == EventAssociationStatus.ASSOCIATED for item in associations
        )
        if not observations:
            state.capability_gaps.append(
                "No qualifying visual analytical observation was produced."
            )
        return (
            f"Associated {associated_count} of {len(assets)} admitted assets and "
            f"produced {len(observations)} analytical observations."
        )

    def _now(self) -> datetime:
        value = self._dependencies.clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class BuildCommonOperationalPictureTool:
    description = ToolDescription(
        "build_common_operational_picture",
        "Build a validated renderer-independent COP from provenance-complete "
        "analytical artifacts.",
        ("multimodal_state",),
        (),
        ("common_operational_picture",),
        (SourceInformationRole.MAP_LAYERS.value,),
        False,
    )

    def __init__(self, dependencies: MultimodalToolDependencies) -> None:
        self._dependencies = dependencies

    async def execute(self, state: AgentExecutionState) -> str:
        multimodal_state = state.workspace.multimodal_state
        if multimodal_state is None:
            raise ValueError("COP generation requires versioned multimodal state.")
        created_at = self._dependencies.clock()
        cop = self._dependencies.cop_builder.build(
            multimodal_state,
            created_at=created_at,
        )
        state.workspace.common_operational_picture = cop
        if cop is None:
            state.capability_gaps.append(
                "No qualifying provenance-complete map feature could be generated."
            )
            return "No common operational picture was generated."
        return f"Built COP {cop.cop_id} with {len(cop.layers)} validated layers."
