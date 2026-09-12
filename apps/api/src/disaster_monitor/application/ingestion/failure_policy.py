"""Application-owned failure classification and bounded retry policy."""

from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_RETRY_DELAY_SECONDS = 300
SOURCE_NOT_REGISTERED_ERROR_CODE = "source_not_registered"
SCHEDULED_REQUEST_NOT_REGISTERED_ERROR_CODE = "scheduled_request_not_registered"


@dataclass(frozen=True, slots=True)
class IngestionFailureDecision:
    """Public disposition for one failed ingestion execution."""

    error_code: str
    retryable: bool
    retry_at: datetime | None

    def __post_init__(self) -> None:
        if not self.error_code.strip():
            raise ValueError("Ingestion failure decisions require an error code.")
        if self.retryable != (self.retry_at is not None):
            raise ValueError(
                "Retryable ingestion failures require a next retry time, and "
                "terminal failures must not have one."
            )
        if self.retry_at is not None and self.retry_at.tzinfo is None:
            raise ValueError("Ingestion retry times must be timezone-aware.")

    @property
    def terminal(self) -> bool:
        return not self.retryable


def classify_ingestion_failure(
    error: Exception,
    *,
    failed_at: datetime,
    attempt_count: int,
) -> IngestionFailureDecision:
    """Map an execution exception to a stable public disposition."""
    if failed_at.tzinfo is None:
        raise ValueError("Ingestion failure times must be timezone-aware.")
    if isinstance(error, TimeoutError):
        return IngestionFailureDecision(
            "timeout", True, failed_at + bounded_retry_delay(attempt_count)
        )
    if isinstance(error, ValueError):
        return IngestionFailureDecision("invalid_payload", False, None)
    return IngestionFailureDecision(
        "provider_failure", True, failed_at + bounded_retry_delay(attempt_count)
    )


def bounded_retry_delay(attempt_count: int) -> timedelta:
    """Return the bounded exponential delay for a claimed attempt."""
    if attempt_count < 0:
        raise ValueError("Ingestion attempt counts cannot be negative.")
    return timedelta(seconds=min(MAX_RETRY_DELAY_SECONDS, 2**attempt_count))


def terminal_failure(error_code: str) -> IngestionFailureDecision:
    """Create a terminal decision for a missing registration or similar boundary."""
    return IngestionFailureDecision(error_code, False, None)
