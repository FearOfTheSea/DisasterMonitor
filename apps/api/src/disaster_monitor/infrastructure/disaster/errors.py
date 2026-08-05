"""Errors raised while translating external disaster feeds."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    """Safe transport/translation metadata retained until composition."""

    reason_code: str
    retryable: bool = False
    http_status: int | None = None
    detail: str | None = None


class DisasterProviderError(RuntimeError):
    """Base error for a provider transport or response problem."""

    def __init__(self, message: str, *, failure: ProviderFailure | None = None) -> None:
        super().__init__(message)
        self.failure = failure or ProviderFailure("network_error")


class DisasterProviderResponseError(DisasterProviderError):
    """The provider returned an unsupported or malformed payload."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "invalid_payload",
        detail: str | None = None,
    ) -> None:
        super().__init__(
            message,
            failure=ProviderFailure(reason_code, detail=detail),
        )
