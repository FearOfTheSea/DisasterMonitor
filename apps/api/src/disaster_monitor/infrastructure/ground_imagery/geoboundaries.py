"""Bounded, pinned geoBoundaries gbOpen administrative lookup."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from disaster_monitor.application.ports.ground_imagery.places import (
    PlaceBoundary,
    PlaceBoundaryLookup,
    PlaceBoundaryLookupError,
)
from disaster_monitor.domain.imagery.regions import (
    MultiPolygon,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)

DEFAULT_GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen"
_API_HOST = "www.geoboundaries.org"
_DOWNLOAD_HOSTS = {
    "geoboundaries.org",
    "www.geoboundaries.org",
    "github.com",
    "raw.githubusercontent.com",
}
_SAFE_COUNTRY = re.compile(r"^[A-Z]{3}$")
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class GeoBoundariesPlaceLookup(PlaceBoundaryLookup):
    """Resolve exact administrative names inside one ISO alpha-3 country.

    Metadata and geometry are cached in-process for the life of the API
    process.  Every result retains the returned boundary ID, source revision,
    represented year, download URL, and checksum so a durable caller can pin
    the exact boundary used for a region version.
    """

    def __init__(
        self,
        *,
        api_base: str = DEFAULT_GEOBOUNDARIES_API,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
        maximum_response_bytes: int = _MAX_RESPONSE_BYTES,
    ) -> None:
        _validate_api_url(api_base)
        if not 100_000 <= maximum_response_bytes <= _MAX_RESPONSE_BYTES:
            raise ValueError(
                "The geoBoundaries response limit must be between 100 KB and 10 MB."
            )
        self._api_base = api_base.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._maximum_response_bytes = maximum_response_bytes
        self._cache: dict[tuple[str, int], tuple[PlaceBoundary, ...]] = {}

    async def find(
        self,
        *,
        name: str,
        country_code: str,
        admin_context: str | None = None,
    ) -> tuple[PlaceBoundary, ...]:
        del admin_context
        normalized_name = _normalize_name(name)
        country = country_code.strip().upper()
        if not normalized_name or not _SAFE_COUNTRY.fullmatch(country):
            return ()
        matches: list[PlaceBoundary] = []
        for level in (1, 2):
            boundaries = await self._boundaries(country, level)
            matches.extend(
                item
                for item in boundaries
                if _normalize_name(item.name) == normalized_name
            )
        return tuple(
            sorted(matches, key=lambda item: (item.admin_level, item.boundary_id))
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _boundaries(
        self, country_code: str, admin_level: int
    ) -> tuple[PlaceBoundary, ...]:
        key = (country_code, admin_level)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        metadata_url = f"{self._api_base}/{country_code}/ADM{admin_level}/"
        metadata = await self._get_json(metadata_url)
        records = _metadata_records(metadata)
        boundaries: list[PlaceBoundary] = []
        for record in records:
            boundary = await self._boundary_from_metadata(
                record, country_code, admin_level
            )
            if boundary is not None:
                boundaries.append(boundary)
        result = tuple(boundaries)
        self._cache[key] = result
        return result

    async def _boundary_from_metadata(
        self, record: dict[str, object], country_code: str, admin_level: int
    ) -> PlaceBoundary | None:
        name = _first_string(record, "boundaryName", "name", "shapeName")
        boundary_id = _first_string(record, "boundaryID", "boundaryId", "id")
        download_url = _first_string(
            record,
            "gjDownloadURL",
            "geojsonDownloadURL",
            "staticDownloadLink",
            "simplifiedGeometryGeoJSON",
        )
        if name is None or boundary_id is None or download_url is None:
            return None
        _validate_download_url(download_url)
        raw = await self._get_bytes(download_url)
        try:
            geometry_document = json.loads(raw)
            geometry, geometry_name = _geometry_from_document(geometry_document)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise PlaceBoundaryLookupError(
                "geoBoundaries returned an unsupported boundary geometry."
            ) from error
        checksum = hashlib.sha256(raw).hexdigest()
        source_revision = (
            _first_string(record, "version", "staticDownloadLink") or "current"
        )
        represented_year = _integer(record.get("year")) or datetime.now(UTC).year
        attribution = _first_string(record, "license", "licenseDetail", "licenseURL")
        source = RegionSource(
            source_id=f"geoboundaries:{boundary_id}",
            source_kind=RegionSourceKind.REPORTED_PLACE,
            publisher="geoBoundaries",
            reference=download_url,
            captured_at=datetime.now(UTC),
            represented_year=represented_year,
            attribution=attribution,
            metadata=(
                ("boundary_id", boundary_id),
                ("static_revision", source_revision),
                ("checksum", checksum),
            ),
        )
        return PlaceBoundary(
            boundary_id=boundary_id,
            name=geometry_name or name,
            country_code=country_code,
            admin_level=admin_level,
            represented_year=represented_year,
            geometry=geometry,
            source=source,
            static_revision=source_revision,
            checksum=checksum,
        )

    async def _get_json(self, url: str) -> object:
        raw = await self._get_bytes(url)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise PlaceBoundaryLookupError(
                "geoBoundaries returned invalid JSON metadata."
            ) from error

    async def _get_bytes(self, url: str) -> bytes:
        try:
            response = await self._client.get(
                url,
                headers={"Accept": "application/json, application/geo+json"},
                follow_redirects=False,
            )
        except httpx.TimeoutException as error:
            raise PlaceBoundaryLookupError(
                "The geoBoundaries lookup timed out."
            ) from error
        except httpx.HTTPError as error:
            raise PlaceBoundaryLookupError(
                "The geoBoundaries lookup failed."
            ) from error
        if response.status_code >= 400:
            raise PlaceBoundaryLookupError(
                f"geoBoundaries rejected the lookup with HTTP {response.status_code}."
            )
        content_length = response.headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > self._maximum_response_bytes
        ):
            raise PlaceBoundaryLookupError(
                "The geoBoundaries response exceeded its size limit."
            )
        if len(response.content) > self._maximum_response_bytes:
            raise PlaceBoundaryLookupError(
                "The geoBoundaries response exceeded its size limit."
            )
        return response.content


def _metadata_records(value: object) -> tuple[dict[str, object], ...]:
    if isinstance(value, dict):
        nested = value.get("boundaries")
        if isinstance(nested, list):
            return tuple(item for item in nested if isinstance(item, dict))
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, dict))
    raise PlaceBoundaryLookupError("geoBoundaries returned invalid metadata.")


def _geometry_from_document(value: object) -> tuple[MultiPolygon, str | None]:
    if not isinstance(value, dict):
        raise ValueError("Boundary geometry must be an object.")
    if value.get("type") in {"Polygon", "MultiPolygon"}:
        return polygon_from_geojson(value), None
    if value.get("type") == "Feature":
        properties = value.get("properties")
        name = (
            _first_string(properties, "shapeName", "name", "boundaryName")
            if isinstance(properties, dict)
            else None
        )
        geometry = value.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError("A boundary feature has no geometry.")
        feature_geometry, _ = _geometry_from_document(geometry)
        return feature_geometry, name
    if value.get("type") == "FeatureCollection":
        features = value.get("features")
        if not isinstance(features, list) or not features:
            raise ValueError("A boundary feature collection is empty.")
        geometries: list[MultiPolygon] = []
        names: list[str] = []
        for item in features:
            geometry, name = _geometry_from_document(item)
            geometries.append(geometry)
            if name:
                names.append(name)
        return (
            MultiPolygon(
                tuple(
                    polygon for geometry in geometries for polygon in geometry.polygons
                )
            ),
            names[0] if names else None,
        )
    raise ValueError("Boundary geometry must be Polygon, MultiPolygon, or Feature.")


def _first_string(value: object, *names: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for name in names:
        candidate = value.get(name)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return "".join(
        character
        for character in normalized
        if character.isalnum() or character.isspace()
    ).strip()


def _validate_api_url(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _API_HOST
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(
            "geoBoundaries API URLs must use the registered HTTPS authority."
        )


def _validate_download_url(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _DOWNLOAD_HOSTS
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise PlaceBoundaryLookupError(
            "geoBoundaries returned a download URL outside the registered authorities."
        )
