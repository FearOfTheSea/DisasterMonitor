"""Serialization from application/domain results to HTTP response models."""

from typing import Literal, cast

from fastapi import Request

from disaster_monitor.application.agent.investigation_cases import (
    InvestigationCaseArtifact,
)
from disaster_monitor.application.agent.operator_actions import (
    IncidentWatchOperatorAction,
    OperatorAction,
    OperatorActionType,
)
from disaster_monitor.application.disaster import SelectedEventSummary
from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.application.media import DisasterMediaGallery
from disaster_monitor.domain.decision import DecisionSupportArtifact
from disaster_monitor.domain.models import MapNavigationAction
from disaster_monitor.presentation.http.common_response_serialization import (
    _cyclone_map_layer_response,
    _event_geometry_response,
    _source_response,
)
from disaster_monitor.presentation.http.multimodal_serialization import (
    cop_response,
    multimodal_state_response,
)
from disaster_monitor.presentation.http.schemas import (
    AssistantOperatorActionResponse,
    AssistantResponse,
    CompoundHazardCorrelationResponse,
    CreateIncidentWatchOperatorActionResponse,
    CrossHazardAssessmentResponse,
    DecisionEstimateResponse,
    DecisionFactResponse,
    DecisionSupportResponse,
    DisasterMediaGalleryResponse,
    DisasterMediaItemResponse,
    EventMeasurementResponse,
    InvestigationCaseCountryResponse,
    InvestigationCaseResponse,
    InvestigationResponse,
    InvestigationTargetResponse,
    MapNavigationActionResponse,
    OpenPanelOperatorActionResponse,
    OperatorActionScopeResponse,
    ReportSectionResponse,
    SelectedEventResponse,
    SetTimeWindowOperatorActionResponse,
    ShowLayerOperatorActionResponse,
    SourceResponse,
)


def _assistant_response(
    result: AssistantAnswer, http_request: Request
) -> AssistantResponse:
    investigation = (
        None
        if result.investigation is None
        else InvestigationResponse(
            status=result.investigation.status,
            task_summary=result.investigation.task_summary,
            disaster=result.investigation.disaster,
            country=result.investigation.country,
            information_needs=list(result.investigation.information_needs),
            output_modalities=list(result.investigation.output_modalities),
            actions=list(result.investigation.actions),
            source_ids=list(result.investigation.source_ids),
            evidence_count=result.investigation.evidence_count,
            capability_gaps=list(result.investigation.capability_gaps),
            termination_reason=result.investigation.termination_reason,
            geographic_scope=result.investigation.geographic_scope,
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
            physical_event_id=result.investigation.physical_event_id,
            evidence_state_version=result.investigation.evidence_state_version,
            specialist_model_call_count=(
                result.investigation.specialist_model_call_count
            ),
            specialist_fallback_reason=(
                result.investigation.specialist_fallback_reason
            ),
            specialist_provenance_validation_failures=(
                result.investigation.specialist_provenance_validation_failures
            ),
            specialist_latency_ms=result.investigation.specialist_latency_ms,
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
                operator_actions=_operator_actions_response(result.operator_actions),
            )
        return AssistantResponse(
            message=result.message,
            conversation_id=result.conversation_id,
            model=result.model,
            operator_actions=_operator_actions_response(result.operator_actions),
        )
    selected_event = result.selected_event
    return AssistantResponse(
        message=result.message,
        conversation_id=result.conversation_id,
        model=result.model,
        map_action=_map_action_response(result.map_action),
        operator_actions=_operator_actions_response(result.operator_actions),
        response_type=result.response_type,
        selected_event=(
            None
            if selected_event is None
            else SelectedEventResponse(
                event_id=selected_event.event_id,
                disaster=selected_event.disaster,
                location=selected_event.location,
                event_time=selected_event.event_time,
                geometry=_event_geometry_response(selected_event.geometry),
                measurements=[
                    EventMeasurementResponse(
                        kind=item.kind,
                        value=item.value,
                        unit=item.unit,
                        source_id=item.source.source_id,
                    )
                    for item in selected_event.measurements
                ],
                provider_ids=list(selected_event.provider_ids),
                geography_status=selected_event.geography_status,
                supplemental_geometry=[
                    _cyclone_map_layer_response(layer)
                    for layer in selected_event.supplemental_geometry
                ],
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
        media_gallery=_media_gallery_response(result.media_gallery, http_request),
        investigation_case=_investigation_case_response(result.investigation_case),
    )


def _investigation_case_response(
    case: InvestigationCaseArtifact | None,
) -> InvestigationCaseResponse | None:
    if case is None:
        return None
    return InvestigationCaseResponse(
        case_id=case.case_id,
        country=InvestigationCaseCountryResponse(
            country_code=case.country.country_code,
            country_name=case.country.country_name,
        ),
        status=case.status.value,
        partial=case.partial,
        targets=[
            InvestigationTargetResponse(
                target_id=branch.target.target_id,
                disaster=branch.target.disaster,
                status=cast(
                    Literal["completed", "partial", "coverage_unavailable", "failed"],
                    branch.status.value,
                ),
                selected_event=_selected_event_response(branch.selected_event),
                sources=[_source_response(source) for source in branch.sources],
                warnings=list(branch.warnings),
                sections=[
                    ReportSectionResponse(title=section.title, content=section.content)
                    for section in branch.sections
                ],
                partial=branch.partial,
                termination_reason=branch.termination_reason,
            )
            for branch in case.targets
        ],
        cross_hazard_assessment=CrossHazardAssessmentResponse(
            status=case.cross_hazard_assessment.status.value,
            summary=case.cross_hazard_assessment.summary,
            limitation=case.cross_hazard_assessment.limitation,
        ),
        correlations=[
            CompoundHazardCorrelationResponse(
                correlation_id=item.correlation_id,
                rule_id=item.rule_id,
                relationship=item.relationship.value,
                first_event_id=item.first_event_id,
                first_physical_event_id=item.first_physical_event_id,
                first_disaster=item.first_disaster,
                second_event_id=item.second_event_id,
                second_physical_event_id=item.second_physical_event_id,
                second_disaster=item.second_disaster,
                distance_km=item.distance_km,
                time_delta_seconds=item.time_delta_seconds,
                source_ids=list(item.source_ids),
                summary=item.summary,
                limitation=item.limitation,
            )
            for item in case.correlations
        ],
    )


def _selected_event_response(
    selected_event: SelectedEventSummary | None,
) -> SelectedEventResponse | None:
    if selected_event is None:
        return None
    return SelectedEventResponse(
        event_id=selected_event.event_id,
        disaster=selected_event.disaster,
        location=selected_event.location,
        event_time=selected_event.event_time,
        geometry=_event_geometry_response(selected_event.geometry),
        measurements=[
            EventMeasurementResponse(
                kind=item.kind,
                value=item.value,
                unit=item.unit,
                source_id=item.source.source_id,
            )
            for item in selected_event.measurements
        ],
        provider_ids=list(selected_event.provider_ids),
        geography_status=selected_event.geography_status,
        supplemental_geometry=[
            _cyclone_map_layer_response(layer)
            for layer in selected_event.supplemental_geometry
        ],
        source=_source_response(selected_event.source),
    )


def _media_gallery_response(
    value: DisasterMediaGallery | None, request: Request
) -> DisasterMediaGalleryResponse | None:
    if value is None:
        return None
    return DisasterMediaGalleryResponse(
        event_id=value.event_id,
        physical_event_id=value.physical_event_id,
        generated_at=value.generated_at,
        rejected_count=value.rejected_count,
        provider_ids=list(value.provider_ids),
        warnings=list(value.warnings),
        items=[
            DisasterMediaItemResponse(
                media_id=item.media_id,
                image_url=str(
                    request.url_for("event_media_asset", media_id=item.media_id)
                ),
                event_id=item.event_id,
                physical_event_id=item.physical_event_id,
                source_id=item.source_id,
                publisher=item.publisher,
                source_page_url=item.source_page_url,
                caption=item.caption,
                credit=item.credit,
                credit_kind=item.credit_kind.value,
                published_at=item.published_at,
                captured_at=item.captured_at,
                license_name=item.license_name,
                license_url=item.license_url,
                rights_status=item.rights_status.value,
                role=item.role.value,
                association_status=item.association_status.value,
                association_rule_ids=list(item.association_rule_ids),
                association_detail=item.association_detail,
                uncertainty=item.uncertainty,
                content_sha256=item.content_sha256,
                width=item.width,
                height=item.height,
            )
            for item in value.items
        ],
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


def _operator_actions_response(
    actions: tuple[OperatorAction, ...],
) -> list[AssistantOperatorActionResponse]:
    return [_operator_action_response(action) for action in actions]


def _operator_action_response(
    action: OperatorAction,
) -> AssistantOperatorActionResponse:
    if isinstance(action, IncidentWatchOperatorAction):
        return CreateIncidentWatchOperatorActionResponse(
            action_id=action.action_id,
            action_type="create_incident_watch",
            risk="confirmation_required",
            disaster=action.disaster,
            scope=OperatorActionScopeResponse(
                kind=action.scope.kind.value,
                country_code=action.scope.country_code,
                country_name=action.scope.country_name,
            ),
            refresh_interval_seconds=cast(
                Literal[900, 1800, 3600, 21600, 86400],
                action.refresh_interval_seconds,
            ),
            label=action.user_safe_label,
        )
    if action.action_type is OperatorActionType.OPEN_PANEL:
        return OpenPanelOperatorActionResponse(
            action_id=action.action_id,
            action_type="open_panel",
            risk="automatic",
            operation="open",
            target="panel",
            value=cast(
                Literal["findings", "sources", "watches", "operations"],
                action.value,
            ),
            label=action.user_safe_label,
        )
    if action.action_type is OperatorActionType.SET_TIME_WINDOW:
        return SetTimeWindowOperatorActionResponse(
            action_id=action.action_id,
            action_type="set_time_window",
            risk="automatic",
            operation="set",
            target="time_window",
            value=cast(Literal["1h", "6h", "24h", "48h", "7d"], action.value),
            label=action.user_safe_label,
        )
    return ShowLayerOperatorActionResponse(
        action_id=action.action_id,
        action_type="show_layer",
        risk="automatic",
        operation="show",
        target="map_layer",
        value=cast(
            Literal[
                "active-incidents",
                "satellite-imagery",
                "cop-evidence",
                "cyclone-supplemental",
                "authoritative-weather-alerts",
                "compound-correlations",
            ],
            action.value,
        ),
        label=action.user_safe_label,
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
