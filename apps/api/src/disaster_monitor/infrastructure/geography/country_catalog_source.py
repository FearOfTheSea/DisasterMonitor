"""Autonomous, fail-closed generation and promotion of global country metadata."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx

_GITHUB_REPOSITORY = "nvkelso/natural-earth-vector"
_LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{_GITHUB_REPOSITORY}/releases/latest"
)
_TAG_REFERENCE_URL = f"https://api.github.com/repos/{_GITHUB_REPOSITORY}/git/ref/tags"
_TAG_OBJECT_URL = f"https://api.github.com/repos/{_GITHUB_REPOSITORY}/git/tags"
_NATURAL_EARTH_PATH = "geojson/ne_50m_admin_0_countries.geojson"
_IANA_TZDATA_URL = "https://data.iana.org/time-zones/tzdata-latest.tar.gz"
_ALLOWED_HOSTS = frozenset(
    {"api.github.com", "raw.githubusercontent.com", "data.iana.org"}
)
_RELEASE_TAG = re.compile(r"v\d+\.\d+\.\d+")
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class CountryCatalogSourceSnapshot:
    """Immutable bytes and revisions admitted from the two allowlisted sources."""

    natural_earth_version: str
    natural_earth_revision: str
    natural_earth_published_at: str
    natural_earth_url: str
    natural_earth_bytes: bytes
    tzdata_url: str
    tzdata_bytes: bytes


class CountryCatalogSource(Protocol):
    """Acquire one complete candidate input snapshot."""

    async def fetch(self) -> CountryCatalogSourceSnapshot: ...

    async def aclose(self) -> None: ...


class NaturalEarthCountryCatalogSource:
    """Fetch a released Natural Earth revision plus the latest IANA tzdata."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_response_bytes = max_response_bytes
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "DisasterMonitor-country-catalog/1.0"},
        )
        self._owns_client = client is None

    async def fetch(self) -> CountryCatalogSourceSnapshot:
        release = _json_object(await self._get(_LATEST_RELEASE_URL, limit=1_000_000))
        tag = _required_string(release, "tag_name")
        published_at = _required_string(release, "published_at")
        if not _RELEASE_TAG.fullmatch(tag):
            raise ValueError("Natural Earth latest release tag is not versioned.")
        revision = await self._resolve_revision(tag)
        geography_url = (
            "https://raw.githubusercontent.com/"
            f"{_GITHUB_REPOSITORY}/{revision}/{_NATURAL_EARTH_PATH}"
        )
        geography_bytes, tzdata_bytes = await asyncio.gather(
            self._get(geography_url),
            self._get(_IANA_TZDATA_URL),
        )
        return CountryCatalogSourceSnapshot(
            natural_earth_version=tag,
            natural_earth_revision=revision,
            natural_earth_published_at=published_at,
            natural_earth_url=geography_url,
            natural_earth_bytes=geography_bytes,
            tzdata_url=_IANA_TZDATA_URL,
            tzdata_bytes=tzdata_bytes,
        )

    async def _resolve_revision(self, tag: str) -> str:
        reference = _json_object(
            await self._get(f"{_TAG_REFERENCE_URL}/{tag}", limit=1_000_000)
        )
        target = _json_object(reference.get("object"))
        revision = _required_string(target, "sha")
        object_type = _required_string(target, "type")
        for _ in range(2):
            if object_type == "commit":
                break
            if object_type != "tag" or not _COMMIT_SHA.fullmatch(revision):
                raise ValueError("Natural Earth release does not resolve to a commit.")
            tag_object = _json_object(
                await self._get(f"{_TAG_OBJECT_URL}/{revision}", limit=1_000_000)
            )
            target = _json_object(tag_object.get("object"))
            revision = _required_string(target, "sha")
            object_type = _required_string(target, "type")
        if object_type != "commit" or not _COMMIT_SHA.fullmatch(revision):
            raise ValueError("Natural Earth release commit is invalid.")
        return revision

    async def _get(self, url: str, *, limit: int | None = None) -> bytes:
        expected_limit = limit or self._max_response_bytes
        _validate_url(url)
        content = bytearray()
        async with self._client.stream("GET", url) as response:
            response.raise_for_status()
            _validate_url(str(response.url))
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > expected_limit:
                    raise ValueError(
                        "Country catalog source response exceeded its limit."
                    )
        if not content:
            raise ValueError("Country catalog source returned an empty response.")
        return bytes(content)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("Country catalog source escaped its HTTPS authority.")


def _json_object(value: object) -> Mapping[str, Any]:
    if isinstance(value, bytes):
        try:
            value = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Country catalog source returned invalid JSON.") from error
    if not isinstance(value, Mapping):
        raise ValueError("Country catalog source JSON must be an object.")
    return cast(Mapping[str, Any], value)


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"Country catalog source is missing {key}.")
    return item.strip()
