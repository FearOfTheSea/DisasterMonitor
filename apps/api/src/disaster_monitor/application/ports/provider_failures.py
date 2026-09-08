"""Typed provider outcomes shared by adapters and application boundaries."""

from enum import StrEnum


class ProviderFailureReason(StrEnum):
    """Closed vocabulary for provider retrieval and admission outcomes."""

    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    RATE_LIMIT = "rate_limited"
    RATE_LIMITED = "rate_limited"
    CONFIGURATION_REJECTED = "configuration_rejected"
    ENDPOINT_MISSING = "endpoint_missing"
    INVALID_PAYLOAD = "invalid_payload"
    MALFORMED_JSON = "malformed_json"
    POLICY_REJECTION = "policy_rejection"
    INCOMPLETE_SCAN = "incomplete_scan"
    EMPTY_RESULT = "empty_result"
    UNEXPECTED_CONTENT_TYPE = "unexpected_content_type"
    RESPONSE_TOO_LARGE = "response_too_large"
    INVALID_RECORD = "invalid_record"
    INVALID_GEOMETRY = "invalid_geometry"
    COUNTRY_PROJECTION_UNUSABLE = "country_projection_unusable"
    SOURCE_POLICY_VIOLATION = "source_policy_violation"
    INVALID_SCHEMA = "invalid_schema"
    HTTP_CLIENT_ERROR = "http_client_error"
    HTTP_SERVER_ERROR = "http_server_error"
    PAGINATION_LIMIT_REACHED = "pagination_limit_reached"

    @property
    def retryable(self) -> bool:
        """Return whether a bounded retry can reasonably change the outcome."""
        return self in {
            self.TIMEOUT,
            self.NETWORK_ERROR,
            self.RATE_LIMIT,
            self.INCOMPLETE_SCAN,
        }
