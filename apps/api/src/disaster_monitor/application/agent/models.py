"""Typed, user-inspectable models for bounded disaster investigations."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from disaster_monitor.application.disaster import (
    DisasterQuery,
    DisasterReport,
    EvidencePacket,
    GeographicScope,
    ProviderBatch,
    WorldwideDisasterQuery,
)
from disaster_monitor.domain.coordination import (
    CollaborativeInvestigation,
    CoordinationSupervision,
    HandoffArtifactType,
    SpecialistHandoff,
)
from disaster_monitor.domain.decision import (
    DecisionExecutionOutcome,
    DecisionSupportArtifact,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EvidenceWorldState,
    HypothesisArtifact,
    IncidentPriorityAssessment,
    InternalTriageDecision,
    PhysicalEventIdentity,
    SituationReport,
)
from disaster_monitor.domain.memory import MemoryContextArtifact
from disaster_monitor.domain.multimodal import (
    AssetEventAssociation,
    CommonOperationalPicture,
    MultimodalAsset,
    MultimodalEvidenceState,
    VisualObservation,
)


class TaskKind(StrEnum):
    NON_DISASTER = "non_disaster"
    GENERAL_KNOWLEDGE = "general_knowledge"
    INVESTIGATION = "investigation"


class InformationNeed(StrEnum):
    EVENT_OVERVIEW = "event_overview"
    FATALITIES = "fatalities"
    INJURIES = "injuries"
    MISSING_PERSONS = "missing_persons"
    EVACUATIONS = "evacuations"
    PHYSICAL_DAMAGE = "physical_damage"
    INFRASTRUCTURE_DISRUPTION = "infrastructure_disruption"
    WARNINGS = "warnings"
    EMERGENCY_RESPONSE = "emergency_response"
    GENERAL_INFORMATION = "general_information"
    IMAGES = "images"
    MAP_VISUALIZATION = "map_visualization"
    TIMELINE = "timeline"
    DECISION_SUPPORT = "decision_support"


class OutputModality(StrEnum):
    TEXT = "text"
    FOCUSED_FACT = "focused_fact"
    TABLE = "table"
    IMAGES = "images"
    MAP = "map"
    TIMELINE = "timeline"


class ValidationStatus(StrEnum):
    VALID = "valid"
    CLARIFICATION_REQUIRED = "clarification_required"
    CATALOG_LIMITATION = "catalog_limitation"
    COVERAGE_UNAVAILABLE = "coverage_unavailable"


class PlanStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentStatus(StrEnum):
    DELEGATED = "delegated"
    CLARIFICATION_REQUIRED = "clarification_required"
    COVERAGE_UNAVAILABLE = "coverage_unavailable"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ReviewDecision(StrEnum):
    FINISH = "finish"
    REPLAN = "replan"
    CLARIFY = "clarify"


class SourceInformationRole(StrEnum):
    EVENT_DISCOVERY = "event_discovery"
    SCIENTIFIC_EVENT_VERIFICATION = "scientific_event_verification"
    OFFICIAL_WARNING = "official_warning"
    CASUALTY_REPORTING = "casualty_reporting"
    PHYSICAL_DAMAGE = "physical_damage"
    INFRASTRUCTURE_STATUS = "infrastructure_status"
    EMERGENCY_RESPONSE = "emergency_response"
    HUMANITARIAN_REPORTING = "humanitarian_situation_reporting"
    SATELLITE_OBSERVATION = "satellite_observation"
    ANALYTICAL_MODEL = "analytical_model"
    IMAGERY = "imagery"
    MAP_LAYERS = "map_layers"


@dataclass(frozen=True, slots=True)
class DisasterTaskDraft:
    disaster_related: bool
    current_or_event_specific: bool
    disaster_mentions: tuple[str, ...] = ()
    place_mentions: tuple[str, ...] = ()
    time_expression: str | None = None
    information_needs: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    event_discriminators: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    clarification_question: str | None = None
    task_kind: TaskKind | None = None
    disaster: Disaster | None = None
    country_code: str | None = None
    country_name: str | None = None
    geographic_scope: GeographicScope | None = None
    date_from: str | None = None
    date_to: str | None = None
    requested_response_language: str | None = None
    response_language_explicit: bool = False
    worldwide_selection: str | None = None
    canonical: bool = False

    def __post_init__(self) -> None:
        if (
            self.task_kind is not None
            or self.disaster is not None
            or self.country_code is not None
            or self.country_name is not None
            or self.geographic_scope is not None
            or self.date_from is not None
            or self.date_to is not None
            or self.requested_response_language is not None
        ):
            object.__setattr__(self, "canonical", True)


@dataclass(frozen=True, slots=True)
class ValidatedDisasterTask:
    question: str
    kind: TaskKind
    requires_evidence: bool
    disaster: Disaster | None = None
    country: Country | None = None
    geographic_scope: GeographicScope = GeographicScope.COUNTRY
    unresolved_place: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    event_discriminators: tuple[str, ...] = ()
    information_needs: tuple[InformationNeed, ...] = ()
    output_modalities: tuple[OutputModality, ...] = (OutputModality.TEXT,)
    validation_status: ValidationStatus = ValidationStatus.VALID
    detail: str | None = None
    query: DisasterQuery | None = None
    worldwide_query: WorldwideDisasterQuery | None = None
    response_language: str | None = None
    response_language_explicit: bool = False


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    tool_name: str
    arguments: tuple[tuple[str, str], ...]
    purpose: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InvestigationPlan:
    plan_id: str
    objective: str
    steps: tuple[PlanStep, ...]
    maximum_steps: int = 8
    status: PlanStatus = PlanStatus.READY
    capability_gaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InvestigationAction:
    step_id: str
    description: str
    status: str = "completed"


@dataclass(frozen=True, slots=True)
class SourceSelectionSummary:
    configured_source_ids: tuple[str, ...] = ()
    unconfigured_source_ids: tuple[str, ...] = ()
    known_not_executable_source_ids: tuple[str, ...] = ()
    supplementary_source_ids: tuple[str, ...] = ()
    unsupported_roles: tuple[str, ...] = ()
    coverage_gaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SpecialistProjectionItem:
    """One bounded canonical value exposed read-only to a specialist model."""

    key: str
    value: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpecialistArtifactProjection:
    """Compact typed projection with no provider or mutation capability."""

    artifact_id: str
    artifact_type: HandoffArtifactType
    state_version: str
    physical_event_id: str
    items: tuple[SpecialistProjectionItem, ...]
    admitted_evidence_ids: tuple[str, ...]
    admitted_source_ids: tuple[str, ...]


@dataclass(slots=True)
class EvidenceWorkspace:
    source_selection: SourceSelectionSummary | None = None
    event_batch: ProviderBatch[DisasterEvent] | None = None
    physical_events: tuple[PhysicalEventIdentity, ...] = ()
    selected_physical_event: PhysicalEventIdentity | None = None
    selected_event: DisasterEvent | None = None
    alternatives: tuple[DisasterEvent, ...] = ()
    situation_batch: ProviderBatch[SituationReport] | None = None
    evidence_state: EvidenceWorldState | None = None
    hypotheses: tuple[HypothesisArtifact, ...] = ()
    incident_priority: IncidentPriorityAssessment | None = None
    triage_decision: InternalTriageDecision | None = None
    decision_support: DecisionSupportArtifact | None = None
    decision_outcome: DecisionExecutionOutcome | None = None
    specialist_handoffs: tuple[SpecialistHandoff, ...] = ()
    collaborative_investigation: CollaborativeInvestigation | None = None
    coordination_supervision: CoordinationSupervision | None = None
    evidence_packet: EvidencePacket | None = None
    report: DisasterReport | None = None
    multimodal_assets: tuple[MultimodalAsset, ...] = ()
    multimodal_associations: tuple[AssetEventAssociation, ...] = ()
    visual_observations: tuple[VisualObservation, ...] = ()
    multimodal_state: MultimodalEvidenceState | None = None
    common_operational_picture: CommonOperationalPicture | None = None
    memory_context: MemoryContextArtifact | None = None
    source_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentExecutionState:
    task: ValidatedDisasterTask
    plan: InvestigationPlan
    conversation_id: str | None = None
    workspace: EvidenceWorkspace = field(default_factory=EvidenceWorkspace)
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    tool_call_count: int = 0
    model_call_count: int = 0
    specialist_model_call_count: int = 0
    visual_model_call_count: int = 0
    replan_count: int = 0
    warnings: list[str] = field(default_factory=list)
    capability_gaps: list[str] = field(default_factory=list)
    actions: list[InvestigationAction] = field(default_factory=list)
    final_status: AgentStatus = AgentStatus.FAILED
    termination_reason: str = "not_started"
    specialist_fallback_reason: str | None = None
    specialist_provenance_validation_failures: int = 0
    specialist_latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class AgentReview:
    decision: ReviewDecision
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    source_id: str
    organization_name: str
    display_name: str
    jurisdiction: str
    authority_level: str
    information_roles: tuple[SourceInformationRole, ...]
    supported_disasters: tuple[Disaster, ...]
    country_codes: tuple[str, ...] | None
    supported_languages: tuple[str, ...]
    endpoint_kind: str
    requires_configuration: bool
    configured: bool
    expected_freshness: str
    attribution_guidance: str
    limitations: tuple[str, ...]
    registered_tool_names: tuple[str, ...]
    provider_registration_name: str
    implementation_status: str
    geographic_scopes: tuple[GeographicScope, ...]
    allowed_hosts: tuple[str, ...] = ()
    documentation_path: str | None = None
