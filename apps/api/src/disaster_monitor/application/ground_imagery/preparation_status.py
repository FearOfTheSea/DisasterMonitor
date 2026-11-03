"""Recover only the failed immutable preparation; keep other failure evidence."""

from dataclasses import replace
from datetime import datetime

from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestState,
    ImageryPreparationFailure,
)


def record_preparation_failure(
    request: GroundImageryRequest,
    selection_id: str,
    artifact_id: str,
    failed_at: datetime,
) -> GroundImageryRequest:
    matches = tuple(
        item
        for item in request.preparation_failures
        if (item.request_version, item.selection_id, item.artifact_id)
        == (request.request_version, selection_id, artifact_id)
    )
    unknown = request.preparation_failure_scope_unknown or (
        "artifact_preparation_failed" in request.reason_codes
        and not request.preparation_failures
    )
    failure = ImageryPreparationFailure(
        request_version=request.request_version,
        selection_id=selection_id,
        artifact_id=artifact_id,
        failed_at=failed_at,
        failure_count=1 + sum(item.failure_count for item in matches),
    )
    return replace(
        request,
        preparation_failures=tuple(
            item for item in request.preparation_failures if item not in matches
        )
        + (failure,),
        preparation_failure_scope_unknown=unknown,
    )


def recover_preparation_failure(
    request: GroundImageryRequest,
    selection_id: str,
    artifact_id: str,
    recovered_at: datetime,
) -> GroundImageryRequest:
    failures = tuple(
        replace(item, recovered_at=max(recovered_at, item.failed_at))
        if item.request_version == request.request_version
        and item.selection_id == selection_id
        and item.artifact_id == artifact_id
        and item.recovered_at is None
        else item
        for item in request.preparation_failures
    )
    updated = replace(request, preparation_failures=failures)
    # Old documents did not retain a target. Success on a different preparation
    # cannot safely resolve an unattributed historical failure.
    if not has_unresolved_preparation_failure(updated):
        updated = replace(
            updated,
            reason_codes=tuple(
                code
                for code in updated.reason_codes
                if code != "artifact_preparation_failed"
            ),
        )
    return updated


def has_unresolved_preparation_failure(request: GroundImageryRequest) -> bool:
    return (
        request.preparation_failure_scope_unknown
        or any(
            item.request_version == request.request_version
            and item.recovered_at is None
            for item in request.preparation_failures
        )
        or (
            "artifact_preparation_failed" in request.reason_codes
            and not request.preparation_failures
        )
    )


def local_preparation_state(request: GroundImageryRequest) -> GroundImageryRequestState:
    if has_unresolved_preparation_failure(request):
        return (
            GroundImageryRequestState.PARTIAL
            if request.artifacts
            else GroundImageryRequestState.FAILED
        )
    return (
        GroundImageryRequestState.READY
        if request.selection is not None
        and all(
            request.selection.for_sensor(sensor).has_observation
            for sensor in request.requested_sensors
        )
        else GroundImageryRequestState.PARTIAL
    )
