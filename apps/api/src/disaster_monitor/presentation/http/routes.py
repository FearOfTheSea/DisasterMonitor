"""FastAPI routes for the MVP."""

import base64
import binascii
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from disaster_monitor.application.assistant_message_payload import (
    assistant_answer_from_payload,
)
from disaster_monitor.application.dto import AssistantAnswer, ModelReadiness
from disaster_monitor.application.media import DisasterMediaGallery
from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.ports.event_media import MediaAssetStore
from disaster_monitor.application.ports.geography import (
    CountryCatalogUpdateAutomation,
    CountryCatalogUpdateStatus,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.operator_identity import (
    TrustedOperatorIdentityPolicy,
)
from disaster_monitor.application.ports.satellite_imagery import SatelliteTileRequest
from disaster_monitor.application.satellite_imagery import (
    SatelliteImageryInputError,
    SatelliteImageryService,
    SatelliteImageryUnavailableError,
    SatelliteImageryUpstreamError,
)
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsQuery,
    ActiveIncidentsService,
)
from disaster_monitor.application.services.provider_freshness import (
    ProviderFreshnessService,
)
from disaster_monitor.application.use_cases.delete_conversation import (
    DeleteConversation,
)
from disaster_monitor.application.use_cases.manage_incident_watches import (
    IncidentWatchNotFoundError,
    InvalidIncidentWatchScopeError,
    ManageIncidentWatches,
)
from disaster_monitor.application.use_cases.record_operator_action import (
    RecordOperatorAction,
    UnknownEvidenceStateError,
)
from disaster_monitor.application.use_cases.run_conversation_turn import (
    RunConversationTurn,
)
from disaster_monitor.domain.decision import DecisionSupportArtifact
from disaster_monitor.domain.disaster import (
    EventGeometry,
    IncidentWatch,
    IncidentWatchChange,
    SourceReference,
    WatchIncident,
    WatchScopeKind,
)
from disaster_monitor.domain.models import MapNavigationAction, MapView
from disaster_monitor.presentation.http.metrics import OperationalMetrics
from disaster_monitor.presentation.http.multimodal_schemas import (
    MultimodalAssetRequest,
)
from disaster_monitor.presentation.http.multimodal_serialization import (
    cop_response,
    multimodal_state_response,
)
from disaster_monitor.presentation.http.schemas import (
    ActiveIncidentResponse,
    ActiveIncidentsSnapshotResponse,
    AssistantRequest,
    AssistantResponse,
    ConversationMessageResponse,
    ConversationResponse,
    ConversationSummaryResponse,
    CountryCatalogSourceResponse,
    CountryCatalogUpdateResponse,
    DecisionEstimateResponse,
    DecisionFactResponse,
    DecisionSupportResponse,
    DisasterIncidentCoverageResponse,
    DisasterMediaGalleryResponse,
    DisasterMediaItemResponse,
    EventCoordinateResponse,
    EventGeometryResponse,
    EventMeasurementResponse,
    EvidenceSnapshotResponse,
    HealthResponse,
    IncidentWatchChangeResponse,
    IncidentWatchCreateRequest,
    IncidentWatchEnabledRequest,
    IncidentWatchEventResponse,
    IncidentWatchMarkReadRequest,
    IncidentWatchMarkReadResponse,
    IncidentWatchResponse,
    IncidentWatchScopeResponse,
    InvestigationResponse,
    MapNavigationActionResponse,
    OperatorActionRequest,
    OperatorActionResponse,
    ProviderFreshnessResponse,
    ReadinessResponse,
    ReportSectionResponse,
    SatelliteImageryCatalogResponse,
    SatelliteImageryProductResponse,
    SelectedEventResponse,
    SourceResponse,
)

router = APIRouter()


def get_conversation_store(request: Request) -> ConversationStore:
    """Retrieve the conversation repository built by the composition root."""
    return cast(ConversationStore, request.app.state.dependencies.conversation_store)


def get_conversation_turn(request: Request) -> RunConversationTurn:
    """Retrieve the transcript-aware assistant use case."""
    return cast(
        RunConversationTurn, request.app.state.dependencies.run_conversation_turn
    )


def get_delete_conversation(request: Request) -> DeleteConversation:
    """Retrieve the atomic conversation-deletion use case."""
    return cast(DeleteConversation, request.app.state.dependencies.delete_conversation)


def get_language_model(request: Request) -> LanguageModel:
    """Retrieve the provider-neutral model port built by the composition root."""
    return cast(LanguageModel, request.app.state.dependencies.language_model)


def get_active_incidents_service(request: Request) -> ActiveIncidentsService:
    """Retrieve the provider-backed incident discovery use case."""
    return cast(ActiveIncidentsService, request.app.state.dependencies.active_incidents)


def get_incident_watches(request: Request) -> ManageIncidentWatches:
    return cast(ManageIncidentWatches, request.app.state.dependencies.incident_watches)


def get_satellite_imagery_service(request: Request) -> SatelliteImageryService:
    """Retrieve the validated imagery use case built by the composition root."""
    return cast(
        SatelliteImageryService, request.app.state.dependencies.satellite_imagery
    )


def _event_geometry_response(
    geometry: EventGeometry | None,
) -> EventGeometryResponse | None:
    if geometry is None:
        return None
    return EventGeometryResponse(
        kind=geometry.kind.value,
        coordinates=[
            EventCoordinateResponse(
                latitude=point.latitude,
                longitude=point.longitude,
            )
            for point in geometry.coordinates
        ],
        description=geometry.description,
        source_id=geometry.source.source_id,
        estimated=geometry.estimated,
    )


def _incident_watch_response(watch: IncidentWatch) -> IncidentWatchResponse:
    return IncidentWatchResponse(
        watch_id=watch.watch_id,
        disaster=watch.disaster,
        scope=IncidentWatchScopeResponse(
            kind=watch.scope.kind.value,
            country_code=watch.scope.country_code,
            country_name=watch.scope.country_name,
        ),
        enabled=watch.enabled,
        refresh_interval_seconds=watch.refresh_interval_seconds,
        created_at=watch.created_at,
        updated_at=watch.updated_at,
        next_refresh_at=watch.next_refresh_at,
        last_checked_at=watch.last_checked_at,
        coverage_state=(
            watch.coverage_state.value if watch.coverage_state is not None else None
        ),
        unread_change_count=watch.unread_change_count,
    )


def _incident_watch_event_response(
    incident: WatchIncident,
) -> IncidentWatchEventResponse:
    return IncidentWatchEventResponse(
        physical_event_id=incident.physical_event_id,
        event_id=incident.event_id,
        disaster=incident.disaster,
        location=incident.location,
        event_time=incident.event_time,
        geometry=_event_geometry_response(incident.geometry),
        measurements=[
            EventMeasurementResponse(
                kind=item.kind,
                value=item.value,
                unit=item.unit,
                source_id=item.source.source_id,
            )
            for item in incident.measurements
        ],
        provider_ids=list(incident.provider_ids),
        provider_tier=incident.provider_tier,
        source_authority=incident.source_authority,
        source=_source_response(incident.source),
        evidence_sources=[_source_response(item) for item in incident.evidence_sources],
    )


def _source_response(source: SourceReference) -> SourceResponse:
    return SourceResponse(
        source_id=source.source_id,
        publisher=source.publisher,
        title=source.title,
        canonical_url=source.canonical_url,
        published_at=source.published_at,
        updated_at=source.updated_at,
        retrieved_at=source.retrieved_at,
        snapshot_id=source.snapshot_id,
    )


def _incident_watch_change_response(
    change: IncidentWatchChange,
) -> IncidentWatchChangeResponse:
    return IncidentWatchChangeResponse(
        change_id=change.change_id,
        watch_id=change.watch_id,
        kind=change.kind.value,
        summary=change.summary,
        detail=change.detail,
        created_at=change.created_at,
        read_at=change.read_at,
        source_ids=list(change.source_ids),
        observation_id=change.observation_id,
        previous_observation_id=change.previous_observation_id,
        before_hash=change.before_hash,
        after_hash=change.after_hash,
        incident=(
            _incident_watch_event_response(change.incident)
            if change.incident is not None
            else None
        ),
    )


def get_media_asset_store(request: Request) -> MediaAssetStore:
    return cast(MediaAssetStore, request.app.state.dependencies.media_assets)


def get_operational_repository(request: Request) -> OperationalRepository:
    """Retrieve the operational store built by the composition root."""
    return cast(
        OperationalRepository, request.app.state.dependencies.operational_repository
    )


def get_operational_metrics() -> OperationalMetrics:
    """Require the HTTP bootstrap to provide its presentation metrics adapter."""
    raise RuntimeError("Operational metrics were not configured.")


def get_provider_freshness(request: Request) -> ProviderFreshnessService:
    return cast(
        ProviderFreshnessService, request.app.state.dependencies.provider_freshness
    )


def get_record_operator_action(request: Request) -> RecordOperatorAction:
    return cast(
        RecordOperatorAction, request.app.state.dependencies.record_operator_action
    )


def get_trusted_operator_identity_policy(
    request: Request,
) -> TrustedOperatorIdentityPolicy:
    """Retrieve the application-facing identity policy from the composition root."""
    return cast(
        TrustedOperatorIdentityPolicy,
        request.app.state.dependencies.operator_identity,
    )


def get_country_catalog_automation(request: Request) -> CountryCatalogUpdateAutomation:
    """Retrieve autonomous catalog updates from the composition root."""
    return cast(
        CountryCatalogUpdateAutomation,
        request.app.state.dependencies.country_catalog_automation,
    )


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Return liveness without contacting Ollama."""
    return HealthResponse(status="ok", service="disaster-monitor-api", version="0.1.0")


@router.get(
    "/satellite-imagery",
    response_model=SatelliteImageryCatalogResponse,
    tags=["satellite-imagery"],
)
async def satellite_imagery_catalog(
    service: Annotated[SatelliteImageryService, Depends(get_satellite_imagery_service)],
) -> SatelliteImageryCatalogResponse:
    """Return product capabilities and configuration availability without secrets."""
    return SatelliteImageryCatalogResponse(
        products=[
            SatelliteImageryProductResponse(
                source_id=product.source_id,
                display_name=product.display_name,
                provider_id=product.provider_id,
                provider_name=product.provider_name,
                temporal_mode=product.temporal_mode,
                temporal_step_minutes=product.temporal_step_minutes,
                attribution=product.attribution,
                maximum_useful_zoom=product.maximum_useful_zoom,
                access_mode=product.access_mode,
                available=product.available,
            )
            for product in service.catalog()
        ]
    )


@router.get(
    "/satellite-imagery/tiles/{provider_id}/{source_id}/{z}/{x}/{y}",
    tags=["satellite-imagery"],
)
async def satellite_imagery_tile(
    provider_id: str,
    source_id: str,
    z: int,
    x: int,
    y: int,
    service: Annotated[SatelliteImageryService, Depends(get_satellite_imagery_service)],
    time: Annotated[str | None, Query(min_length=10, max_length=32)] = None,
) -> Response:
    """Fetch one validated protected tile from a fixed configured upstream."""
    try:
        tile = await service.fetch_tile(
            SatelliteTileRequest(provider_id, source_id, z, x, y, time)
        )
    except SatelliteImageryInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SatelliteImageryUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except SatelliteImageryUpstreamError as error:
        status_code = 504 if error.reason_code == "timeout" else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return Response(
        content=tile.content,
        media_type=tile.media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get(
    "/incidents",
    response_model=ActiveIncidentsSnapshotResponse,
    tags=["incidents"],
)
async def active_incidents(
    service: Annotated[ActiveIncidentsService, Depends(get_active_incidents_service)],
    time_window_days: Annotated[int, Query(ge=1, le=30)] = 7,
    limit_per_disaster: Annotated[int, Query(ge=1, le=20)] = 10,
) -> ActiveIncidentsSnapshotResponse:
    """Return bounded, source-backed worldwide events without model inference."""
    snapshot = await service.execute(
        ActiveIncidentsQuery(
            time_window_days=time_window_days,
            limit_per_disaster=limit_per_disaster,
        )
    )
    return ActiveIncidentsSnapshotResponse(
        retrieved_at=snapshot.retrieved_at,
        incidents=[
            ActiveIncidentResponse(
                event_id=incident.event_id,
                disaster=incident.disaster,
                location=incident.location,
                event_time=incident.event_time,
                geometry=_event_geometry_response(incident.geometry),
                measurements=[
                    EventMeasurementResponse(
                        kind=measurement.kind,
                        value=measurement.value,
                        unit=measurement.unit,
                        source_id=measurement.source.source_id,
                    )
                    for measurement in incident.measurements
                ],
                provider_ids=list(incident.provider_ids),
                provider_tier=incident.provider_tier,
                source_authority=incident.source_authority,
                source=_source_response(incident.source),
            )
            for incident in snapshot.incidents
        ],
        coverage=[
            DisasterIncidentCoverageResponse(
                disaster=item.disaster,
                state=item.state.value,
                incident_count=item.incident_count,
                providers=list(item.providers),
                detail=item.detail,
            )
            for item in snapshot.coverage
        ],
        warnings=list(snapshot.warnings),
    )


@router.post(
    "/incident-watches",
    response_model=IncidentWatchResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["incident-watches"],
)
async def create_incident_watch(
    body: IncidentWatchCreateRequest,
    use_case: Annotated[ManageIncidentWatches, Depends(get_incident_watches)],
) -> IncidentWatchResponse:
    """Create one bounded local watch for a disaster and canonical scope."""
    try:
        watch = await use_case.create(
            disaster=body.disaster,
            scope_kind=WatchScopeKind(body.scope.kind),
            country=getattr(body.scope, "country", None),
            refresh_interval_seconds=body.refresh_interval_seconds,
        )
    except (InvalidIncidentWatchScopeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _incident_watch_response(watch)


@router.get(
    "/incident-watches",
    response_model=list[IncidentWatchResponse],
    tags=["incident-watches"],
)
async def list_incident_watches(
    use_case: Annotated[ManageIncidentWatches, Depends(get_incident_watches)],
) -> list[IncidentWatchResponse]:
    return [_incident_watch_response(item) for item in await use_case.list()]


@router.post(
    "/incident-watches/{watch_id}/enabled",
    response_model=IncidentWatchResponse,
    tags=["incident-watches"],
)
async def set_incident_watch_enabled(
    watch_id: str,
    body: IncidentWatchEnabledRequest,
    use_case: Annotated[ManageIncidentWatches, Depends(get_incident_watches)],
) -> IncidentWatchResponse:
    try:
        watch = await use_case.set_enabled(watch_id, enabled=body.enabled)
    except IncidentWatchNotFoundError:
        raise HTTPException(
            status_code=404, detail="Incident watch not found."
        ) from None
    return _incident_watch_response(watch)


@router.delete(
    "/incident-watches/{watch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["incident-watches"],
)
async def delete_incident_watch(
    watch_id: str,
    use_case: Annotated[ManageIncidentWatches, Depends(get_incident_watches)],
) -> Response:
    try:
        await use_case.delete(watch_id)
    except IncidentWatchNotFoundError:
        raise HTTPException(
            status_code=404, detail="Incident watch not found."
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/incident-watches/{watch_id}/timeline",
    response_model=list[IncidentWatchChangeResponse],
    tags=["incident-watches"],
)
async def incident_watch_timeline(
    watch_id: str,
    use_case: Annotated[ManageIncidentWatches, Depends(get_incident_watches)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[IncidentWatchChangeResponse]:
    try:
        values = await use_case.timeline(watch_id, limit=limit)
    except IncidentWatchNotFoundError:
        raise HTTPException(
            status_code=404, detail="Incident watch not found."
        ) from None
    return [_incident_watch_change_response(item) for item in values]


@router.post(
    "/incident-watches/{watch_id}/timeline/read",
    response_model=IncidentWatchMarkReadResponse,
    tags=["incident-watches"],
)
async def mark_incident_watch_timeline_read(
    watch_id: str,
    body: IncidentWatchMarkReadRequest,
    use_case: Annotated[ManageIncidentWatches, Depends(get_incident_watches)],
) -> IncidentWatchMarkReadResponse:
    try:
        marked, watch = await use_case.mark_read(watch_id, tuple(body.change_ids))
    except IncidentWatchNotFoundError:
        raise HTTPException(
            status_code=404, detail="Incident watch not found."
        ) from None
    return IncidentWatchMarkReadResponse(
        watch_id=watch.watch_id,
        marked_read_count=marked,
        unread_change_count=watch.unread_change_count,
    )


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
    service: Annotated[ProviderFreshnessService, Depends(get_provider_freshness)],
) -> list[ProviderFreshnessResponse]:
    """Expose upstream freshness and failures without hiding unavailable sources."""
    values = await service.list()
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


@router.get(
    "/media/{media_id}",
    name="event_media_asset",
    status_code=status.HTTP_200_OK,
    tags=["assistant"],
)
async def event_media_asset(
    media_id: str,
    store: Annotated[MediaAssetStore, Depends(get_media_asset_store)],
) -> Response:
    """Serve only bounded image bytes already admitted by source-media policy."""
    asset = store.get(media_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media not found."
        )
    return Response(
        content=asset.content,
        media_type=asset.media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
    repository: Annotated[OperationalRepository, Depends(get_operational_repository)],
    operational_metrics: Annotated[
        OperationalMetrics, Depends(get_operational_metrics)
    ],
) -> Response:
    """Expose API and durable queue metrics for an owner-selected scraper."""
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
    policy: Annotated[
        TrustedOperatorIdentityPolicy,
        Depends(get_trusted_operator_identity_policy),
    ],
    use_case: Annotated[RecordOperatorAction, Depends(get_record_operator_action)],
) -> OperatorActionResponse:
    """Record an attributable bounded review from a trusted identity boundary."""
    if not policy.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trusted operator identity is not configured.",
        )
    operator_id = request.headers.get(policy.header_name, "").strip()
    if not operator_id or len(operator_id) > 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A trusted operator identity is required.",
        )
    try:
        result = await use_case.execute(
            operator_id=operator_id,
            decision=body.decision,
            state_version=body.state_version,
            rationale=body.rationale,
            evidence_ids=tuple(body.evidence_ids),
            policy_ids=tuple(body.policy_ids),
        )
    except UnknownEvidenceStateError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The reviewed evidence state does not exist.",
        ) from None
    return OperatorActionResponse(
        action_id=result.action.action_id,
        operator_id=result.action.operator_id,
        state_version=result.action.state_version,
        decision=result.action.decision,
        reviewed_at=result.action.reviewed_at,
        created=result.created,
    )


@router.post(
    "/assistant",
    response_model=AssistantResponse,
    response_model_exclude_unset=True,
    status_code=status.HTTP_200_OK,
    tags=["assistant"],
)
async def assistant(
    body: AssistantRequest,
    http_request: Request,
    use_case: Annotated[RunConversationTurn, Depends(get_conversation_turn)],
) -> AssistantResponse:
    """Answer a map-related question through the application use case."""
    result = await use_case.execute(
        question=body.question,
        conversation_id=body.conversation_id,
        map_view=(
            None
            if body.map_view is None
            else MapView(
                center_latitude=body.map_view.center_latitude,
                center_longitude=body.map_view.center_longitude,
                zoom=body.map_view.zoom,
            )
        ),
        multimodal_inputs=tuple(_asset_input(item) for item in body.multimodal_assets),
    )
    return _assistant_response(result, http_request)


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
    )


@router.get(
    "/conversations",
    response_model=list[ConversationSummaryResponse],
    tags=["assistant"],
)
async def list_conversations(
    repository: Annotated[ConversationStore, Depends(get_conversation_store)],
) -> list[ConversationSummaryResponse]:
    """List durable conversations from newest update to oldest."""
    return [
        ConversationSummaryResponse(
            conversation_id=item.conversation_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            preview=item.preview,
        )
        for item in await repository.list()
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    tags=["assistant"],
)
async def get_conversation(
    conversation_id: str,
    http_request: Request,
    repository: Annotated[ConversationStore, Depends(get_conversation_store)],
) -> ConversationResponse:
    """Return one stored transcript in chronological order."""
    conversation = await repository.get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested conversation does not exist.",
        )
    return ConversationResponse(
        conversation_id=conversation.conversation_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            ConversationMessageResponse(
                id=message.message_id,
                role=message.role.value,
                content=message.content,
                created_at=message.created_at,
                assistant_response=(
                    _assistant_response(answer, http_request)
                    if (
                        answer := assistant_answer_from_payload(
                            message.assistant_payload
                        )
                    )
                    is not None
                    else None
                ),
            )
            for message in conversation.messages
        ],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["assistant"],
)
async def delete_conversation(
    conversation_id: str,
    use_case: Annotated[DeleteConversation, Depends(get_delete_conversation)],
) -> Response:
    """Permanently remove a conversation and all lifecycle-owned state."""
    await use_case.execute(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        declared_disaster=item.declared_disaster,
        declared_country_code=item.declared_country_code,
        capture_role=item.capture_role,
        canonical_url=item.canonical_url,
        dataset_id=item.dataset_id,
        license_name=item.license_name,
        processing_level=item.processing_level,
        parent_asset_ids=tuple(item.parent_asset_ids),
        event_id_hint=item.event_id_hint,
    )
