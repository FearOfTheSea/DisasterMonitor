"""Small shared helpers for bounded JSON feed adapters."""

import json
from typing import Any

import httpx

from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
)


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str | int | float | bool | None] | None = None,
    max_bytes: int = 1_000_000,
) -> Any:
    """Fetch and validate one bounded JSON response."""
    try:
        async with client.stream("GET", url, params=params) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type:
                raise DisasterProviderResponseError(
                    "The source returned an unexpected content type."
                )
            declared_length = response.headers.get("content-length")
            if declared_length is not None:
                try:
                    if int(declared_length) > max_bytes:
                        raise DisasterProviderResponseError(
                            "The source response exceeded the configured size limit."
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
                        "The source response exceeded the configured size limit."
                    )
            content = bytes(body)
    except DisasterProviderResponseError:
        raise
    except httpx.HTTPError as error:
        raise DisasterProviderError("The source network request failed.") from error
    if not content:
        raise DisasterProviderResponseError("The source returned an empty response.")
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise DisasterProviderResponseError(
            "The source returned malformed JSON."
        ) from error
