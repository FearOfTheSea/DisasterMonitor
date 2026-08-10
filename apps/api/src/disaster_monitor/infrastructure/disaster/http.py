"""Small shared helpers for bounded JSON feed adapters."""

import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx

from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
    ProviderFailure,
)

_RETRYABLE_CODES = {"timeout", "network_error", "rate_limited", "http_server_error"}
HttpParam = str | int | float | bool | None | Sequence[str | int | float | bool | None]


def validate_network_target(url: str, allowed_hosts: frozenset[str]) -> None:
    """Reject a provider target outside its registry-owned HTTPS authorities."""
    try:
        target = urlsplit(url)
        port = target.port
    except ValueError as error:
        raise DisasterProviderResponseError(
            "The provider target is invalid.",
            reason_code="source_policy_violation",
        ) from error
    hostname = (target.hostname or "").lower().rstrip(".")
    approved = {item.lower().rstrip(".") for item in allowed_hosts}
    if (
        target.scheme.lower() != "https"
        or not hostname
        or target.username is not None
        or target.password is not None
        or port not in {None, 443}
        or hostname not in approved
    ):
        raise DisasterProviderResponseError(
            "The provider target is outside the approved source authority.",
            reason_code="source_policy_violation",
        )


def _http_failure(error: httpx.HTTPStatusError) -> DisasterProviderError:
    status = error.response.status_code
    if status == 429:
        code = "rate_limited"
        retryable = True
    elif 400 <= status < 500:
        code = (
            "configuration_rejected"
            if status in {400, 401, 403}
            else "http_client_error"
        )
        retryable = False
    else:
        code = "http_server_error"
        retryable = True
    return DisasterProviderError(
        "The source returned an HTTP error.",
        failure=ProviderFailure(code, retryable=retryable, http_status=status),
    )


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, HttpParam] | None = None,
    allowed_hosts: frozenset[str],
    max_bytes: int = 1_000_000,
    provider_name: str = "provider",
) -> Any:
    """Fetch and validate one bounded JSON response."""
    validate_network_target(url, allowed_hosts)
    for attempt in range(2):
        try:
            async with client.stream("GET", url, params=params) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    failure = _http_failure(error)
                    if failure.failure.reason_code in _RETRYABLE_CODES and attempt == 0:
                        continue
                    raise failure from error
                content_type = response.headers.get("content-type", "").lower()
                if "json" not in content_type:
                    raise DisasterProviderResponseError(
                        "The source returned an unexpected content type.",
                        reason_code="unexpected_content_type",
                    )
                declared_length = response.headers.get("content-length")
                if declared_length is not None:
                    try:
                        if int(declared_length) > max_bytes:
                            raise DisasterProviderResponseError(
                                "The source response exceeded the configured size "
                                "limit.",
                                reason_code="response_too_large",
                            )
                    except ValueError:
                        pass
                body = bytearray()
                async for chunk in response.aiter_bytes(
                    chunk_size=max(1, min(max_bytes + 1, 64 * 1024))
                ):
                    remaining = max_bytes + 1 - len(body)
                    body.extend(chunk[:remaining])
                    if len(body) > max_bytes:
                        raise DisasterProviderResponseError(
                            "The source response exceeded the configured size limit.",
                            reason_code="response_too_large",
                        )
                content = bytes(body)
        except DisasterProviderResponseError:
            raise
        except httpx.TimeoutException as error:
            failure = DisasterProviderError(
                "The source request timed out.",
                failure=ProviderFailure("timeout", retryable=True),
            )
            if attempt == 0:
                continue
            raise failure from error
        except httpx.HTTPError as error:
            failure = DisasterProviderError(
                "The source network request failed.",
                failure=ProviderFailure("network_error", retryable=True),
            )
            if attempt == 0:
                continue
            raise failure from error
        else:
            break
    if not content:
        raise DisasterProviderResponseError(
            "The source returned an empty response.", reason_code="empty_result"
        )
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise DisasterProviderResponseError(
            "The source returned malformed JSON.", reason_code="malformed_json"
        ) from error


async def get_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, HttpParam] | None = None,
    allowed_hosts: frozenset[str],
    max_bytes: int = 1_000_000,
    provider_name: str = "provider",
) -> str:
    """Fetch one bounded HTML/text response using the same typed transport rules."""
    validate_network_target(url, allowed_hosts)
    for attempt in range(2):
        try:
            async with client.stream("GET", url, params=params) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    failure = _http_failure(error)
                    if failure.failure.reason_code in _RETRYABLE_CODES and attempt == 0:
                        continue
                    raise failure from error
                content_type = response.headers.get("content-type", "").lower()
                if not any(value in content_type for value in ("text/", "html", "pdf")):
                    raise DisasterProviderResponseError(
                        "The source returned an unexpected content type.",
                        reason_code="unexpected_content_type",
                    )
                declared_length = response.headers.get("content-length")
                if (
                    declared_length is not None
                    and declared_length.isdigit()
                    and int(declared_length) > max_bytes
                ):
                    raise DisasterProviderResponseError(
                        "The source response exceeded the configured size limit.",
                        reason_code="response_too_large",
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes(
                    chunk_size=max(1, min(max_bytes + 1, 64 * 1024))
                ):
                    remaining = max_bytes + 1 - len(body)
                    body.extend(chunk[:remaining])
                    if len(body) > max_bytes:
                        raise DisasterProviderResponseError(
                            "The source response exceeded the configured size limit.",
                            reason_code="response_too_large",
                        )
                content = bytes(body)
        except DisasterProviderResponseError:
            raise
        except httpx.TimeoutException as error:
            failure = DisasterProviderError(
                "The source request timed out.",
                failure=ProviderFailure("timeout", retryable=True),
            )
            if attempt == 0:
                continue
            raise failure from error
        except httpx.HTTPError as error:
            failure = DisasterProviderError(
                "The source network request failed.",
                failure=ProviderFailure("network_error", retryable=True),
            )
            if attempt == 0:
                continue
            raise failure from error
        else:
            break
    if not content:
        raise DisasterProviderResponseError(
            "The source returned an empty response.", reason_code="empty_result"
        )
    return content.decode("utf-8", errors="replace")


async def get_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, HttpParam] | None = None,
    allowed_hosts: frozenset[str],
    max_bytes: int = 1_000_000,
    provider_name: str = "provider",
) -> bytes:
    """Fetch one bounded binary response, retaining the shared failure taxonomy."""
    validate_network_target(url, allowed_hosts)
    for attempt in range(2):
        try:
            async with client.stream("GET", url, params=params) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    failure = _http_failure(error)
                    if failure.failure.reason_code in _RETRYABLE_CODES and attempt == 0:
                        continue
                    raise failure from error
                body = bytearray()
                async for chunk in response.aiter_bytes(
                    chunk_size=max(1, min(max_bytes + 1, 64 * 1024))
                ):
                    remaining = max_bytes + 1 - len(body)
                    body.extend(chunk[:remaining])
                    if len(body) > max_bytes:
                        raise DisasterProviderResponseError(
                            "The source response exceeded the configured size limit.",
                            reason_code="response_too_large",
                        )
                content = bytes(body)
        except DisasterProviderResponseError:
            raise
        except httpx.TimeoutException as error:
            failure = DisasterProviderError(
                "The source request timed out.",
                failure=ProviderFailure("timeout", retryable=True),
            )
            if attempt == 0:
                continue
            raise failure from error
        except httpx.HTTPError as error:
            failure = DisasterProviderError(
                "The source network request failed.",
                failure=ProviderFailure("network_error", retryable=True),
            )
            if attempt == 0:
                continue
            raise failure from error
        else:
            break
    if not content:
        raise DisasterProviderResponseError(
            "The source returned an empty response.", reason_code="empty_result"
        )
    return content
