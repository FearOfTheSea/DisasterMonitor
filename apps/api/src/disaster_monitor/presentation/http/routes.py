"""FastAPI routes for the MVP."""

import base64
import binascii
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from disaster_monitor.application.dto import ModelReadiness
from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.geography import (
    CountryCatalogUpdateAutomation,
    CountryCatalogUpdateStatus,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.services.operational_ingestion import (
    record_operator_review,
)
from disaster_monitor.application.use_cases.answer_map_question import AnswerMapQuestion
from disaster_monitor.domain.decision import DecisionSupportArtifact
from disaster_monitor.domain.models import MapNavigationAction, MapView
from disaster_monitor.domain.operations import OperatorActionRecord
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.presentation.http.metrics import OperationalMetrics
from disaster_monitor.presentation.http.multimodal_schemas import (
    MultimodalAssetRequest,
)
from disaster_monitor.presentation.http.multimodal_serialization import (
    cop_response,
    multimodal_state_response,
)
from disaster_monitor.presentation.http.schemas import (
    AssistantRequest,
    AssistantResponse,
    CountryCatalogSourceResponse,
    CountryCatalogUpdateResponse,
    DecisionEstimateResponse,
    DecisionFactResponse,
    DecisionSupportResponse,
    EvidenceSnapshotResponse,
    HealthResponse,
    InvestigationResponse,
    MapNavigationActionResponse,
    OperatorActionRequest,
    OperatorActionResponse,
    ProviderFreshnessResponse,
    ReadinessResponse,
    ReportSectionResponse,
    SelectedEventResponse,
    SourceResponse,
)

router = APIRouter()


def get_answer_use_case(request: Request) -> AnswerMapQuestion:
    """Retrieve the use case built by the composition root."""
    return cast(AnswerMapQuestion, request.app.state.answer_map_question)


def get_language_model(request: Request) -> LanguageModel:
    """Retrieve the provider-neutral model port built by the composition root."""
    return cast(LanguageModel, request.app.state.language_model)


def get_operational_repository(request: Request) -> OperationalRepository:
    """Retrieve the operational store built by the composition root."""
    return cast(OperationalRepository, request.app.state.operational_repository)


def get_country_catalog_automation(request: Request) -> CountryCatalogUpdateAutomation:
    """Retrieve autonomous catalog updates from the composition root."""
    return cast(
        CountryCatalogUpdateAutomation,
        request.app.state.country_catalog_automation,
    )


_FRESHNESS_EXPECTATIONS = {
    "jma-rolling-earthquakes": timedelta(minutes=15),
    "jma-significant-earthquakes": timedelta(hours=24),
    "usgs-earthquakes": timedelta(minutes=15),
    "fdma-situation-reports": timedelta(hours=6),
    "jma-tsunami-status": timedelta(minutes=15),
    "reliefweb-situation-reports": timedelta(hours=6),
    "nchmf-vietnam-warnings": timedelta(hours=1),
    "nasa-firms-active-fire": timedelta(hours=3),
    "copernicus-gfm-vietnam": timedelta(hours=1),
}


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Return liveness without contacting Ollama."""
    return HealthResponse(status="ok", service="disaster-monitor-api", version="0.1.0")


@router.get("/ready", response_model=ReadinessResponse, tags=["system"])
async def readiness(
    language_model: Annotated[LanguageModel, Depends(get_language_model)],
) -> ReadinessResponse:
    """Check local Ollama and the configured Qwen model without inference."""
    result: ModelReadiness = await language_model.check_readiness()
    return ReadinessResponse(
        status="ready"
        if result.ollama_available and result.model_available
        else "unavailable",
        ollama_available=result.ollama_available,
        model_available=result.model_available,
        model=result.model,
    )


@router.get(
    "/operations/providers",
    response_model=list[ProviderFreshnessResponse],
    tags=["operations"],
)
async def provider_freshness(
    repository: Annotated[OperationalRepository, Depends(get_operational_repository)],
) -> list[ProviderFreshnessResponse]:
    """Expose upstream freshness and failures without hiding unavailable sources."""
    values = await repository.freshness(
        now=datetime.now(UTC), expectations=_FRESHNESS_EXPECTATIONS
    )
    return [
        ProviderFreshnessResponse(
            source_id=item.source_id,
            state=item.state.value,
            last_attempt_at=item.last_attempt_at,
            last_success_at=item.last_success_at,
            effective_at=item.effective_at,
            age_seconds=item.age_seconds,
            expected_freshness_seconds=item.expected_freshness_seconds,
            consecutive_failures=item.consecutive_failures,
            latest_error_code=item.latest_error_code,
        )
        for item in values
    ]


@router.get(
    "/operations/country-catalog",
    response_model=CountryCatalogUpdateResponse,
    tags=["operations"],
)
async def country_catalog_status(
    automation: Annotated[
        CountryCatalogUpdateAutomation, Depends(get_country_catalog_automation)
    ],
) -> CountryCatalogUpdateResponse:
    """Expose active provenance and the next autonomous monthly attempt."""
    return _country_catalog_response(automation.status())


@router.post(
    "/operations/country-catalog/update",
    response_model=CountryCatalogUpdateResponse,
    tags=["operations"],
)
async def update_country_catalog(
    automation: Annotated[
        CountryCatalogUpdateAutomation, Depends(get_country_catalog_automation)
    ],
) -> CountryCatalogUpdateResponse:
    """Run the same fail-closed path used by monthly automation immediately."""
    result = await automation.request_update(CountryCatalogUpdateTrigger.MANUAL)
    return _country_catalog_response(result)


def _country_catalog_response(
    value: CountryCatalogUpdateStatus,
) -> CountryCatalogUpdateResponse:
    return CountryCatalogUpdateResponse(
        state=value.state.value,
        active_version=value.active_version,
        country_count=value.country_count,
        automatic_updates_enabled=value.automatic_updates_enabled,
        trigger=value.trigger.value if value.trigger else None,
        last_attempt_at=value.last_attempt_at,
        last_success_at=value.last_success_at,
        next_scheduled_at=value.next_scheduled_at,
        message=value.message,
        failure_code=value.failure_code,
        sources=[
            CountryCatalogSourceResponse(
                source_id=source.source_id,
                version=source.version,
                revision=source.revision,
                sha256=source.sha256,
            )
            for source in value.sources
        ],
    )


@router.get("/metrics", tags=["operations"])
async def metrics(
    request: Request,
    repository: Annotated[OperationalRepository, Depends(get_operational_repository)],
) -> Response:
    """Expose API and durable queue metrics for an owner-selected scraper."""
    operational_metrics = cast(
        OperationalMetrics, request.app.state.operational_metrics
    )
    operational_metrics.update_jobs(await repository.job_status_counts())
    content, content_type = operational_metrics.render()
    return Response(content=content, media_type=content_type)


@router.get(
    "/operations/evidence-history",
    response_model=list[EvidenceSnapshotResponse],
    tags=["operations"],
)
async def evidence_history(
    repository: Annotated[OperationalRepository, Depends(get_operational_repository)],
    source_id: str | None = None,
    limit: int = 100,
) -> list[EvidenceSnapshotResponse]:
    """Return bounded immutable snapshot metadata, newest first."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    snapshots = await repository.snapshots(source_id=source_id, limit=limit)
    return [
        EvidenceSnapshotResponse(
            snapshot_id=item.snapshot_id,
            source_id=item.source_id,
            provider_revision=item.provider_revision,
            retrieved_at=item.retrieved_at,
            published_at=item.published_at,
            observed_at=item.observed_at,
            effective_at=item.effective_at,
            content_type=item.content_type,
            payload_sha256=item.payload_sha256,
            payload_size_bytes=item.payload_size_bytes,
            rights_id=item.rights_id,
            content_available=item.content_available,
            content_deleted_at=item.content_deleted_at,
            content_deletion_reason=item.content_deletion_reason,
        )
        for item in snapshots
    ]


@router.post(
    "/operations/operator-actions",
    response_model=OperatorActionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["operations"],
)
async def operator_action(
    body: OperatorActionRequest,
    request: Request,
    repository: Annotated[OperationalRepository, Depends(get_operational_repository)],
) -> OperatorActionResponse:
    """Record an attributable bounded review from a trusted identity boundary."""
    settings = cast(Settings, request.app.state.settings)
    if not settings.trusted_operator_identity_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trusted operator identity is not configured.",
        )
    operator_id = request.headers.get(
        settings.trusted_operator_identity_header, ""
    ).strip()
    if not operator_id or len(operator_id) > 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A trusted operator identity is required.",
        )
    if not await repository.world_state_exists(body.state_version):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The reviewed evidence state does not exist.",
        )
    reviewed_at = datetime.now(UTC)
    action = OperatorActionRecord(
        action_id=f"operator-action:{uuid4()}",
        operator_id=operator_id,
        decision=body.decision,
        state_version=body.state_version,
        rationale=body.rationale,
        evidence_ids=tuple(dict.fromkeys(body.evidence_ids)),
        policy_ids=tuple(dict.fromkeys(body.policy_ids)),
        reviewed_at=reviewed_at,
    )
    created = await record_operator_review(repository, action)
    return OperatorActionResponse(
        action_id=action.action_id,
        operator_id=operator_id,
        state_version=body.state_version,
        decision=body.decision,
        reviewed_at=reviewed_at,
        created=created,
    )


@router.post(
    "/assistant",
    response_model=AssistantResponse,
    response_model_exclude_unset=True,
    status_code=status.HTTP_200_OK,
    tags=["assistant"],
)
async def assistant(
    request: AssistantRequest,
    use_case: Annotated[AnswerMapQuestion, Depends(get_answer_use_case)],
) -> AssistantResponse:
    """Answer a map-related question through the application use case."""
    result = await use_case.execute(
        question=request.question,
        conversation_id=request.conversation_id,
        map_view=(
            None
            if request.map_view is None
            else MapView(
                center_latitude=request.map_view.center_latitude,
                center_longitude=request.map_view.center_longitude,
                zoom=request.map_view.zoom,
            )
        ),
        multimodal_inputs=tuple(
            _asset_input(item) for item in request.multimodal_assets
        ),
    )
    investigation = (
        None
        if result.investigation is None
        else InvestigationResponse(
            status=result.investigation.status,
            task_summary=result.investigation.task_summary,
            hazard=result.investigation.hazard,
            country=result.investigation.country,
            information_needs=list(result.investigation.information_needs),
            output_modalities=list(result.investigation.output_modalities),
            actions=list(result.investigation.actions),
            source_ids=list(result.investigation.source_ids),
            evidence_count=result.investigation.evidence_count,
            capability_gaps=list(result.investigation.capability_gaps),
            termination_reason=result.investigation.termination_reason,
            triage_priority=result.investigation.triage_priority,
            triage_score=result.investigation.triage_score,
            triage_action=result.investigation.triage_action,
            triage_autonomy_mode=result.investigation.triage_autonomy_mode,
            triage_requires_human_intervention=(
                result.investigation.triage_requires_human_intervention
            ),
            decision_action=result.investigation.decision_action,
            decision_autonomy_mode=result.investigation.decision_autonomy_mode,
            decision_requires_human_intervention=(
                result.investigation.decision_requires_human_intervention
            ),
            decision_termination_reason=(
                result.investigation.decision_termination_reason
            ),
            decision_state_revision=result.investigation.decision_state_revision,
            decision_active_internal_states=list(
                result.investigation.decision_active_internal_states
            ),
            specialist_handoff_count=(result.investigation.specialist_handoff_count),
            specialist_roles=list(result.investigation.specialist_roles),
            collaboration_status=result.investigation.collaboration_status,
            collaboration_finding_count=(
                result.investigation.collaboration_finding_count
            ),
            collaboration_deadlock_count=(
                result.investigation.collaboration_deadlock_count
            ),
            collaboration_iterations=result.investigation.collaboration_iterations,
            collaboration_fallback_reason=(
                result.investigation.collaboration_fallback_reason
            ),
            coordination_supervision_id=(
                result.investigation.coordination_supervision_id
            ),
            coordination_supervisor_status=(
                result.investigation.coordination_supervisor_status
            ),
            coordination_sufficient=result.investigation.coordination_sufficient,
            coordination_required_finding_keys=list(
                result.investigation.coordination_required_finding_keys
            ),
            coordination_missing_finding_keys=list(
                result.investigation.coordination_missing_finding_keys
            ),
            coordination_termination_reason=(
                result.investigation.coordination_termination_reason
            ),
            coordination_final_rationale=(
                result.investigation.coordination_final_rationale
            ),
            coordination_evidence_ids=list(
                result.investigation.coordination_evidence_ids
            ),
            coordination_analytical_focus=(
                result.investigation.coordination_analytical_focus
            ),
            coordination_analytical_parameter_set_id=(
                result.investigation.coordination_analytical_parameter_set_id
            ),
            coordination_analytical_release_id=(
                result.investigation.coordination_analytical_release_id
            ),
        )
    )
    if result.response_type == "assistant":
        map_action = _map_action_response(result.map_action)
        if map_action is not None:
            return AssistantResponse(
                message=result.message,
                conversation_id=result.conversation_id,
                model=result.model,
                map_action=map_action,
            )
        return AssistantResponse(
            message=result.message,
            conversation_id=result.conversation_id,
            model=result.model,
        )
    selected_event = result.selected_event
    return AssistantResponse(
        message=result.message,
        conversation_id=result.conversation_id,
        model=result.model,
        map_action=_map_action_response(result.map_action),
        response_type=result.response_type,
        selected_event=(
            None
            if selected_event is None
            else SelectedEventResponse(
                event_id=selected_event.event_id,
                hazard=selected_event.hazard,
                location=selected_event.location,
                event_time=selected_event.event_time,
                latitude=selected_event.latitude,
                longitude=selected_event.longitude,
                magnitude=selected_event.magnitude,
                intensity=selected_event.intensity,
                depth_km=selected_event.depth_km,
                provider_ids=list(selected_event.provider_ids),
                source=SourceResponse(
                    source_id=selected_event.source.source_id,
                    publisher=selected_event.source.publisher,
                    title=selected_event.source.title,
                    canonical_url=selected_event.source.canonical_url,
                    published_at=selected_event.source.published_at,
                    updated_at=selected_event.source.updated_at,
                    retrieved_at=selected_event.source.retrieved_at,
                    snapshot_id=selected_event.source.snapshot_id,
                ),
            )
        ),
        retrieval_time=result.retrieval_time,
        sources=[
            SourceResponse(
                source_id=source.source_id,
                publisher=source.publisher,
                title=source.title,
                canonical_url=source.canonical_url,
                published_at=source.published_at,
                updated_at=source.updated_at,
                retrieved_at=source.retrieved_at,
                snapshot_id=source.snapshot_id,
            )
            for source in result.sources
        ],
        warnings=list(result.warnings),
        sections=[
            ReportSectionResponse(title=section.title, content=section.content)
            for section in result.sections
        ],
        partial=result.partial,
        investigation=investigation,
        decision_support=_decision_support_response(result.decision_support),
        multimodal=multimodal_state_response(result.multimodal_state),
        common_operational_picture=cop_response(result.common_operational_picture),
    )


def _map_action_response(
    action: MapNavigationAction | None,
) -> MapNavigationActionResponse | None:
    if action is None:
        return None
    return MapNavigationActionResponse(
        type="fit_bounds",
        bounds=action.bounds,
        label=action.label,
        max_zoom=action.max_zoom,
    )


def _decision_support_response(
    artifact: DecisionSupportArtifact | None,
) -> DecisionSupportResponse | None:
    if artifact is None:
        return None
    return DecisionSupportResponse(
        artifact_id=artifact.artifact_id,
        evidence_state_version=artifact.evidence_state_version,
        facts=[
            DecisionFactResponse(
                fact_id=fact.fact_id,
                statement=fact.statement,
                evidence_ids=list(fact.evidence_ids),
                source_ids=list(fact.source_ids),
                status=fact.status,
                statement_type=fact.statement_type.value,
            )
            for fact in artifact.facts
        ],
        estimates=[
            DecisionEstimateResponse(
                estimate_id=estimate.estimate_id,
                proposition=estimate.proposition,
                probability=estimate.probability,
                supporting_evidence_ids=list(estimate.supporting_evidence_ids),
                contradicting_evidence_ids=list(estimate.contradicting_evidence_ids),
                uncertain_evidence_ids=list(estimate.uncertain_evidence_ids),
                rationale_rule_ids=list(estimate.rationale_rule_ids),
                statement_type=estimate.statement_type.value,
            )
            for estimate in artifact.estimates
        ],
        scenario_mode=artifact.scenario_analysis.mode.value,
        recommendation_status=artifact.scenario_analysis.recommendation.status.value,
        advisory_only=artifact.advisory_only,
    )


def _asset_input(item: MultimodalAssetRequest) -> AssetAdmissionInput:
    try:
        content = base64.b64decode(item.content_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(
            status_code=422,
            detail="Multimodal asset content must be valid base64.",
        ) from error
    footprint = item.footprint
    return AssetAdmissionInput(
        content=content,
        attribution=item.attribution,
        captured_at=item.captured_at,
        footprint_coordinates=(
            None
            if footprint is None
            else tuple(
                tuple((longitude, latitude) for longitude, latitude in ring)
                for ring in footprint.coordinates
            )
        ),
        footprint_crs=footprint.crs if footprint else "EPSG:4326",
        declared_hazard=item.declared_hazard,
        declared_country_code=item.declared_country_code,
        capture_role=item.capture_role,
        canonical_url=item.canonical_url,
        dataset_id=item.dataset_id,
        license_name=item.license_name,
        processing_level=item.processing_level,
        parent_asset_ids=tuple(item.parent_asset_ids),
        event_id_hint=item.event_id_hint,
    )
