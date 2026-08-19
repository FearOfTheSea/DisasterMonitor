"""Small shared helpers for bounded JSON feed adapters."""

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from disaster_monitor.application.services.operational_ingestion import (
    AcquiredSourcePayload,
    canonical_request_identity,
)
from disaster_monitor.domain.operations import SourceSnapshotRecord
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
    ProviderFailure,
)

_RETRYABLE_CODES = {"timeout", "network_error", "rate_limited", "http_server_error"}
HttpParam = str | int | float | bool | None | Sequence[str | int | float | bool | None]
SourcePayloadRecorder = Callable[
    [AcquiredSourcePayload], Awaitable[SourceSnapshotRecord]
]


@dataclass(slots=True)
class SnapshotCapture:
    """Registry-bound metadata required to persist one successful response."""

    source_id: str
    request_identity: str
    rights_id: str
    retrieved_at: datetime
    recorder: SourcePayloadRecorder
    snapshot: SourceSnapshotRecord | None = None


def build_snapshot_capture(
    recorder: SourcePayloadRecorder | None,
    *,
    source_id: str,
    parameters: Mapping[str, str],
    rights_id: str,
    retrieved_at: datetime,
) -> SnapshotCapture | None:
    """Build credential-free capture identity for an allowlisted request."""
    if recorder is None:
        return None
    return SnapshotCapture(
        source_id,
        canonical_request_identity(source_id, parameters),
        rights_id,
        retrieved_at,
        recorder,
    )


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
    headers: Mapping[str, str] | None = None,
    capture: SnapshotCapture | None = None,
    allowed_hosts: frozenset[str],
    max_bytes: int = 1_000_000,
    provider_name: str = "provider",
    accepted_content_types: frozenset[str] = frozenset(),
) -> Any:
    """Fetch and validate one bounded JSON response."""
    return await _request_json(
        client,
        url,
        method="GET",
        params=params,
        headers=headers,
        capture=capture,
        allowed_hosts=allowed_hosts,
        max_bytes=max_bytes,
        provider_name=provider_name,
        accepted_content_types=accepted_content_types,
    )


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, HttpParam] | None = None,
    headers: Mapping[str, str] | None = None,
    json_body: object,
    capture: SnapshotCapture | None = None,
    allowed_hosts: frozenset[str],
    max_bytes: int = 1_000_000,
    provider_name: str = "provider",
) -> Any:
    """POST one bounded JSON document using the shared transport rules."""
    try:
        content = json.dumps(
            json_body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DisasterProviderResponseError(
            "The provider request body is not valid JSON.",
            reason_code="invalid_payload",
        ) from error
    request_headers = dict(headers or {})
    request_headers.setdefault("content-type", "application/json")
    return await _request_json(
        client,
        url,
        method="POST",
        params=params,
        headers=request_headers,
        content=content,
        capture=capture,
        allowed_hosts=allowed_hosts,
        max_bytes=max_bytes,
        provider_name=provider_name,
    )


async def _request_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str,
    params: Mapping[str, HttpParam] | None = None,
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
    capture: SnapshotCapture | None = None,
    allowed_hosts: frozenset[str],
    max_bytes: int,
    provider_name: str,
    accepted_content_types: frozenset[str] = frozenset(),
) -> Any:
    """Execute one bounded JSON request with one retry for transient failures."""
    validate_network_target(url, allowed_hosts)
    response_body = b""
    for attempt in range(2):
        try:
            request_kwargs: dict[str, Any] = {
                "params": params,
                "headers": headers,
            }
            if content is not None:
                request_kwargs["content"] = content
            async with client.stream(method, url, **request_kwargs) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    failure = _http_failure(error)
                    if failure.failure.reason_code in _RETRYABLE_CODES and attempt == 0:
                        continue
                    raise failure from error
                content_type = response.headers.get("content-type", "").lower()
                media_type = content_type.partition(";")[0].strip()
                if "json" not in content_type and media_type not in {
                    item.lower() for item in accepted_content_types
                }:
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
                response_body = bytes(body)
                await _capture_response(response, response_body, capture)
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
    if not response_body:
        raise DisasterProviderResponseError(
            "The source returned an empty response.", reason_code="empty_result"
        )
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as error:
        raise DisasterProviderResponseError(
            "The source returned malformed JSON.", reason_code="malformed_json"
        ) from error


async def get_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, HttpParam] | None = None,
    headers: Mapping[str, str] | None = None,
    capture: SnapshotCapture | None = None,
    allowed_hosts: frozenset[str],
    max_bytes: int = 1_000_000,
    provider_name: str = "provider",
) -> str:
    """Fetch one bounded HTML/text response using the same typed transport rules."""
    validate_network_target(url, allowed_hosts)
    for attempt in range(2):
        try:
            async with client.stream(
                "GET", url, params=params, headers=headers
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    failure = _http_failure(error)
                    if failure.failure.reason_code in _RETRYABLE_CODES and attempt == 0:
                        continue
                    raise failure from error
                content_type = response.headers.get("content-type", "").lower()
                if not any(
                    value in content_type
                    for value in ("text/", "html", "pdf", "xml", "rss", "atom")
                ):
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
                await _capture_response(response, content, capture)
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
    headers: Mapping[str, str] | None = None,
    capture: SnapshotCapture | None = None,
    allowed_hosts: frozenset[str],
    max_bytes: int = 1_000_000,
    provider_name: str = "provider",
) -> bytes:
    """Fetch one bounded binary response, retaining the shared failure taxonomy."""
    validate_network_target(url, allowed_hosts)
    for attempt in range(2):
        try:
            async with client.stream(
                "GET", url, params=params, headers=headers
            ) as response:
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
                await _capture_response(response, content, capture)
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


async def _capture_response(
    response: httpx.Response,
    content: bytes,
    capture: SnapshotCapture | None,
) -> None:
    if capture is None:
        return
    revision = response.headers.get("etag") or response.headers.get("last-modified")
    capture.snapshot = await capture.recorder(
        AcquiredSourcePayload(
            source_id=capture.source_id,
            canonical_request_identity=capture.request_identity,
            provider_revision=revision,
            content=content,
            content_type=response.headers.get(
                "content-type", "application/octet-stream"
            ).partition(";")[0],
            response_status=response.status_code,
            retrieved_at=capture.retrieved_at,
            published_at=None,
            observed_at=None,
            rights_id=capture.rights_id,
        )
    )
