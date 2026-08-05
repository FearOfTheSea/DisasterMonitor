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
        response = await client.get(url, params=params)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise DisasterProviderError("The source network request failed.") from error
    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        raise DisasterProviderResponseError(
            "The source returned an unexpected content type."
        )
    if len(response.content) > max_bytes:
        raise DisasterProviderResponseError(
            "The source response exceeded the configured size limit."
        )
    if not response.content:
        raise DisasterProviderResponseError("The source returned an empty response.")
    try:
        return json.loads(response.content)
    except json.JSONDecodeError as error:
        raise DisasterProviderResponseError(
            "The source returned malformed JSON."
        ) from error
