"""Trusted operator identity at the HTTP boundary."""

from typing import cast

from fastapi import HTTPException, Request, status

from disaster_monitor.application.ports.operator_identity import (
    TrustedOperatorIdentityPolicy,
)


def get_trusted_operator_identity_policy(
    request: Request,
) -> TrustedOperatorIdentityPolicy:
    return cast(
        TrustedOperatorIdentityPolicy,
        request.app.state.dependencies.operator_identity,
    )


def trusted_operator_id(request: Request, policy: TrustedOperatorIdentityPolicy) -> str:
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
    return operator_id
