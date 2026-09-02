"""FastAPI routes for the MVP."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.operator_identity import (
    TrustedOperatorIdentityPolicy,
)
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsQuery,
    ActiveIncidentsService,
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
from disaster_monitor.domain.disaster import (
    WatchScopeKind,
)
from disaster_monitor.presentation.http.common_response_serialization import (
    _event_geometry_response,
    _source_response,
)
from disaster_monitor.presentation.http.response_serialization import (
    _incident_watch_change_response,
    _incident_watch_response,
)
from disaster_monitor.presentation.http.schemas import (
    ActiveIncidentResponse,
    ActiveIncidentsSnapshotResponse,
    CompoundHazardCorrelationResponse,
    DisasterIncidentCoverageResponse,
    EventMeasurementResponse,
    EvidenceSnapshotResponse,
    IncidentWatchChangeResponse,
    IncidentWatchCreateRequest,
    IncidentWatchEnabledRequest,
    IncidentWatchMarkReadRequest,
    IncidentWatchMarkReadResponse,
    IncidentWatchResponse,
    OperatorActionRequest,
    OperatorActionResponse,
)

router = APIRouter()


def get_active_incidents_service(request: Request) -> ActiveIncidentsService:
    """Retrieve the provider-backed incident discovery use case."""
    return cast(ActiveIncidentsService, request.app.state.dependencies.active_incidents)


def get_incident_watches(request: Request) -> ManageIncidentWatches:
    return cast(ManageIncidentWatches, request.app.state.dependencies.incident_watches)


def get_operational_repository(request: Request) -> OperationalRepository:
    """Retrieve the operational store built by the composition root."""
    return cast(
        OperationalRepository, request.app.state.dependencies.operational_repository
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
                physical_event_id=incident.physical_event_id,
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
            for item in snapshot.correlations
        ],
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
