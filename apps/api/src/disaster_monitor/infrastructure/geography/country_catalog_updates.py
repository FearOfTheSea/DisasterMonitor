"""Autonomous, fail-closed generation and promotion of global country metadata."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import tarfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx

from disaster_monitor.application.ports.geography import (
    CountryCatalogSourceVersion,
    CountryCatalogUpdateState,
    CountryCatalogUpdateStatus,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
    parse_country_catalog_payload,
)

_LOGGER = logging.getLogger(__name__)
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
_COUNTRY_CODE = re.compile(r"[A-Z]{3}")
_ALPHA2_CODE = re.compile(r"[A-Z]{2}")
_SAFE_VERSION = re.compile(r"[A-Za-z0-9._-]{1,160}")
_SHORT_ALIAS_STOPLIST = frozenset(
    {
        "AM",
        "AN",
        "AS",
        "AT",
        "BE",
        "BY",
        "DO",
        "GO",
        "HE",
        "IN",
        "IS",
        "IT",
        "ME",
        "NO",
        "OF",
        "ON",
        "OR",
        "TO",
        "US",
        "WE",
    }
)
_NATURAL_EARTH_LICENSE = "Natural Earth public domain"
_IANA_TZDATA_LICENSE = "IANA Time Zone Database public domain"


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


class VersionedCountryCatalogStore:
    """Persist immutable candidates and atomically switch the active catalog."""

    def __init__(self, root: Path, catalog: StaticCountryCatalog) -> None:
        self.root = root
        self.active_path = root / "active.json"
        self.status_path = root / "update-status.json"
        self.lock_path = root / "update.lock"
        self._archives = root / "catalogs"
        self._catalog = catalog

    def promote(self, payload: Mapping[str, object], serialized: bytes) -> None:
        metadata, _ = parse_country_catalog_payload(payload)
        version = str(metadata.get("version", ""))
        if not _SAFE_VERSION.fullmatch(version):
            raise ValueError("Generated country catalog version is invalid.")
        self._archives.mkdir(parents=True, exist_ok=True)
        archive = self._archives / f"countries.{version}.json"
        if archive.exists():
            if archive.read_bytes() != serialized:
                raise ValueError(
                    "An immutable country catalog version changed content."
                )
        else:
            _atomic_write(archive, serialized)
        previous = self.active_path.read_bytes() if self.active_path.exists() else None
        _atomic_write(self.active_path, serialized)
        try:
            self._catalog.activate_payload(payload)
            self._catalog.mark_active_path_current()
        except Exception:
            if previous is None:
                self.active_path.unlink(missing_ok=True)
            else:
                _atomic_write(self.active_path, previous)
                restored = cast(dict[str, object], json.loads(previous.decode("utf-8")))
                self._catalog.activate_payload(restored)
                self._catalog.mark_active_path_current()
            raise

    def read_status(self) -> Mapping[str, Any] | None:
        if not self.status_path.is_file():
            return None
        try:
            return _json_object(self.status_path.read_bytes())
        except (OSError, ValueError, TypeError):
            return None

    def write_status(self, status: Mapping[str, object]) -> None:
        serialized = (
            json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n"
        )
        _atomic_write(self.status_path, serialized)

    def acquire_lease(self, now: datetime) -> bool:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError:
            try:
                age = now.timestamp() - self.lock_path.stat().st_mtime
                if age <= 2 * 60 * 60:
                    return False
                self.lock_path.unlink()
            except OSError:
                return False
            return self.acquire_lease(now)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(now.astimezone(UTC).isoformat())
        return True

    def release_lease(self) -> None:
        self.lock_path.unlink(missing_ok=True)


class AutonomousCountryCatalogUpdater:
    """Generate and promote catalogs while retaining the last known-good version."""

    def __init__(
        self,
        *,
        catalog: StaticCountryCatalog,
        store: VersionedCountryCatalogStore,
        source: CountryCatalogSource,
        automatic_updates_enabled: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        minimum_country_count: int = 190,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._source = source
        self._automatic_updates_enabled = automatic_updates_enabled
        self._clock = clock
        self._minimum_country_count = minimum_country_count
        self._lock = asyncio.Lock()

    def status(self) -> CountryCatalogUpdateStatus:
        return _deserialize_status(
            self._store.read_status(),
            catalog=self._catalog,
            automatic_updates_enabled=self._automatic_updates_enabled,
        )

    async def update(
        self, trigger: CountryCatalogUpdateTrigger
    ) -> CountryCatalogUpdateStatus:
        now = _aware_utc(self._clock())
        if self._lock.locked() or not self._store.acquire_lease(now):
            current = self.status()
            return _replace_status(
                current,
                state=CountryCatalogUpdateState.RUNNING,
                trigger=trigger,
                message="A country catalog update is already running.",
            )
        async with self._lock:
            previous = self.status()
            running = _replace_status(
                previous,
                state=CountryCatalogUpdateState.RUNNING,
                trigger=trigger,
                last_attempt_at=now,
                message="Fetching and validating autonomous country metadata.",
                failure_code=None,
            )
            try:
                self._write_status(running)
            except Exception:
                self._store.release_lease()
                raise
            try:
                snapshot = await self._source.fetch()
                payload = build_country_catalog_payload(
                    snapshot, minimum_country_count=self._minimum_country_count
                )
                serialized = serialize_country_catalog(payload)
                metadata = _json_object(payload.get("metadata"))
                version = _required_string(metadata, "version")
                countries = cast(list[object], payload["countries"])
                sources = _source_versions(snapshot)
                if version == previous.active_version:
                    completed = CountryCatalogUpdateStatus(
                        state=CountryCatalogUpdateState.UNCHANGED,
                        active_version=version,
                        country_count=len(countries),
                        automatic_updates_enabled=self._automatic_updates_enabled,
                        trigger=trigger,
                        last_attempt_at=now,
                        last_success_at=now,
                        message=(
                            f"Catalog {version} is already active with "
                            f"{len(countries)} countries."
                        ),
                        sources=sources,
                    )
                else:
                    self._store.promote(payload, serialized)
                    completed = CountryCatalogUpdateStatus(
                        state=CountryCatalogUpdateState.UPDATED,
                        active_version=version,
                        country_count=len(countries),
                        automatic_updates_enabled=self._automatic_updates_enabled,
                        trigger=trigger,
                        last_attempt_at=now,
                        last_success_at=now,
                        message=(
                            f"Promoted catalog {version} with {len(countries)} "
                            "countries after all validation gates passed."
                        ),
                        sources=sources,
                    )
            except Exception as error:
                _LOGGER.exception("Autonomous country catalog update failed closed")
                completed = CountryCatalogUpdateStatus(
                    state=CountryCatalogUpdateState.FAILED,
                    active_version=previous.active_version,
                    country_count=previous.country_count,
                    automatic_updates_enabled=self._automatic_updates_enabled,
                    trigger=trigger,
                    last_attempt_at=now,
                    last_success_at=previous.last_success_at,
                    message=(
                        "Catalog update failed closed; the previous version remains "
                        "active and the scheduler will retry automatically."
                    ),
                    failure_code=_failure_code(error),
                    sources=previous.sources,
                )
            finally:
                self._store.release_lease()
            self._write_status(completed)
            return completed

    def _write_status(self, status: CountryCatalogUpdateStatus) -> None:
        self._store.write_status(_serialize_status(status))

    async def aclose(self) -> None:
        await self._source.aclose()


class CountryCatalogAutomation:
    """Run manual updates and catch-up-safe monthly UTC scheduling."""

    def __init__(
        self,
        updater: AutonomousCountryCatalogUpdater,
        *,
        automatic_updates_enabled: bool,
        retry_interval: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._updater = updater
        self._automatic_updates_enabled = automatic_updates_enabled
        self._retry_interval = retry_interval
        self._clock = clock
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def status(self) -> CountryCatalogUpdateStatus:
        current = self._updater.status()
        next_scheduled = (
            next_country_catalog_update_at(
                current,
                now=_aware_utc(self._clock()),
                retry_interval=self._retry_interval,
            )
            if self._automatic_updates_enabled
            else None
        )
        return _replace_status(current, next_scheduled_at=next_scheduled)

    async def request_update(
        self, trigger: CountryCatalogUpdateTrigger
    ) -> CountryCatalogUpdateStatus:
        await self._updater.update(trigger)
        return self.status()

    async def start(self) -> None:
        if not self._automatic_updates_enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(), name="country-catalog-monthly-updater"
        )

    async def _run(self) -> None:
        while not self._stop.is_set():
            current = self.status()
            now = _aware_utc(self._clock())
            due = current.next_scheduled_at
            if due is not None and due <= now:
                result = await self._updater.update(
                    CountryCatalogUpdateTrigger.SCHEDULED
                )
                current = self.status()
                now = _aware_utc(self._clock())
                due = (
                    now + timedelta(minutes=1)
                    if result.state == CountryCatalogUpdateState.RUNNING
                    else current.next_scheduled_at
                )
            delay = 3600.0
            if due is not None:
                delay = max(1.0, min(delay, (due - now).total_seconds()))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                continue

    async def aclose(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        await self._updater.aclose()


def next_country_catalog_update_at(
    status: CountryCatalogUpdateStatus,
    *,
    now: datetime,
    retry_interval: timedelta,
) -> datetime:
    """Return first-of-month due time or a bounded retry after failure."""
    current = _aware_utc(now)
    month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if status.last_success_at is not None and status.last_success_at >= month_start:
        return _next_month(month_start)
    if (
        status.state == CountryCatalogUpdateState.FAILED
        and status.last_attempt_at is not None
        and status.last_attempt_at >= month_start
    ):
        return status.last_attempt_at + retry_interval
    return month_start


def build_country_catalog_payload(
    snapshot: CountryCatalogSourceSnapshot,
    *,
    minimum_country_count: int = 190,
) -> dict[str, object]:
    """Build deterministic application metadata from immutable upstream bytes."""
    geography = _json_object(snapshot.natural_earth_bytes)
    if geography.get("type") != "FeatureCollection":
        raise ValueError("Natural Earth payload is not a GeoJSON FeatureCollection.")
    raw_features = geography.get("features")
    if not isinstance(raw_features, list):
        raise ValueError("Natural Earth payload has no feature list.")
    timezones, tzdata_version = _parse_tzdata(snapshot.tzdata_bytes)
    records: list[_CountryFeature] = []
    for feature in raw_features:
        record = _feature_record(_json_object(feature))
        if record is not None:
            records.append(record)
    if len(records) < minimum_country_count:
        raise ValueError("Natural Earth did not provide the minimum country coverage.")
    by_code: dict[str, list[_CountryFeature]] = defaultdict(list)
    for record in records:
        by_code[record.alpha3].append(record)
    countries = [
        _merge_country(code, features, timezones)
        for code, features in sorted(by_code.items())
    ]
    _remove_ambiguous_aliases(countries)
    country_payloads = [country.payload() for country in countries]
    natural_hash = hashlib.sha256(snapshot.natural_earth_bytes).hexdigest()
    timezone_hash = hashlib.sha256(snapshot.tzdata_bytes).hexdigest()
    combined = hashlib.sha256(
        f"{snapshot.natural_earth_revision}|{natural_hash}|{tzdata_version}|"
        f"{timezone_hash}".encode()
    ).hexdigest()
    version = (
        f"natural-earth-{snapshot.natural_earth_version.removeprefix('v')}."
        f"tzdb-{tzdata_version}.{combined[:12]}"
    )
    payload: dict[str, object] = {
        "metadata": {
            "version": version,
            "schema_version": "2.0.0",
            "published": snapshot.natural_earth_published_at,
            "country_count": len(country_payloads),
            "sources": [
                {
                    "source_id": "natural-earth-admin-0",
                    "version": snapshot.natural_earth_version,
                    "revision": snapshot.natural_earth_revision,
                    "url": snapshot.natural_earth_url,
                    "sha256": f"sha256:{natural_hash}",
                    "license": _NATURAL_EARTH_LICENSE,
                },
                {
                    "source_id": "iana-tzdata",
                    "version": tzdata_version,
                    "revision": f"sha256:{timezone_hash}",
                    "url": snapshot.tzdata_url,
                    "sha256": f"sha256:{timezone_hash}",
                    "license": _IANA_TZDATA_LICENSE,
                },
            ],
            "license": (
                "Natural Earth is public domain; the IANA Time Zone Database is "
                "public domain."
            ),
            "note": (
                "Natural Earth 1:50m Admin 0 geometries are deterministic query "
                "approximations, not legal borders or maritime claims. Default "
                "timezones are selected deterministically from IANA zone.tab."
            ),
        },
        "countries": country_payloads,
    }
    _validate_generated_payload(payload, minimum_country_count=minimum_country_count)
    return payload


def serialize_country_catalog(payload: Mapping[str, object]) -> bytes:
    """Serialize a catalog reproducibly for immutable version collision checks."""
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )


@dataclass(slots=True)
class _CountryFeature:
    alpha3: str
    alpha2: str | None
    canonical_name: str
    aliases: set[str]
    label_latitude: float
    label_longitude: float
    polygons: list[list[tuple[float, float]]]
    bounds: tuple[float, float, float, float]


@dataclass(slots=True)
class _GeneratedCountry:
    alpha3: str
    canonical_name: str
    aliases: list[str]
    timezone_name: str | None
    bounds: tuple[float, float, float, float]
    polygons: list[list[tuple[float, float]]]

    def payload(self) -> dict[str, object]:
        return {
            "alpha3": self.alpha3,
            "name": self.canonical_name,
            "aliases": self.aliases,
            "timezone": self.timezone_name,
            "bounds": list(self.bounds),
            "polygons": [
                [[latitude, longitude] for latitude, longitude in polygon]
                for polygon in self.polygons
            ],
        }


@dataclass(frozen=True, slots=True)
class _TimezoneChoice:
    name: str
    latitude: float
    longitude: float


def _feature_record(feature: Mapping[str, Any]) -> _CountryFeature | None:
    properties = _json_object(feature.get("properties"))
    geometry = _json_object(feature.get("geometry"))
    alpha3 = _property_code(
        properties, ("ISO_A3", "ADM0_A3", "ISO_A3_EH", "SOV_A3"), _COUNTRY_CODE
    )
    if alpha3 is None:
        return None
    alpha2 = _property_code(properties, ("ISO_A2_EH", "ISO_A2", "WB_A2"), _ALPHA2_CODE)
    canonical_name = _first_property(
        properties, ("NAME_LONG", "NAME_EN", "ADMIN", "NAME")
    )
    if canonical_name is None:
        raise ValueError(f"Natural Earth country {alpha3} has no canonical name.")
    aliases = {
        value
        for key, raw in properties.items()
        if key
        in {
            "ADMIN",
            "NAME",
            "NAME_LONG",
            "FORMAL_EN",
            "FORMAL_FR",
            "NAME_SORT",
            "NAME_CIAWF",
            "ABBREV",
            "POSTAL",
        }
        or key.startswith("NAME_")
        for value in _alias_values(raw)
    }
    if alpha2 is not None and alpha2 not in _SHORT_ALIAS_STOPLIST:
        aliases.add(alpha2)
    polygons = _geometry_polygons(geometry)
    if not polygons:
        raise ValueError(f"Natural Earth country {alpha3} has no usable polygon.")
    latitude_values = [point[0] for polygon in polygons for point in polygon]
    longitude_values = [point[1] for polygon in polygons for point in polygon]
    bounds = (
        round(min(latitude_values), 6),
        round(max(latitude_values), 6),
        round(min(longitude_values), 6),
        round(max(longitude_values), 6),
    )
    label_latitude = _float_property(properties.get("LABEL_Y"), sum(bounds[:2]) / 2)
    label_longitude = _float_property(properties.get("LABEL_X"), sum(bounds[2:]) / 2)
    return _CountryFeature(
        alpha3,
        alpha2,
        canonical_name,
        aliases,
        label_latitude,
        label_longitude,
        polygons,
        bounds,
    )


def _merge_country(
    code: str,
    features: Sequence[_CountryFeature],
    timezones: Mapping[str, tuple[_TimezoneChoice, ...]],
) -> _GeneratedCountry:
    names = {feature.canonical_name for feature in features}
    if len(names) != 1:
        raise ValueError(f"Natural Earth code {code} maps to conflicting names.")
    alpha2_values = {feature.alpha2 for feature in features if feature.alpha2}
    if len(alpha2_values) > 1:
        raise ValueError(
            f"Natural Earth code {code} maps to conflicting alpha-2 codes."
        )
    aliases = {
        alias
        for feature in features
        for alias in feature.aliases
        if _usable_alias(alias)
    }
    canonical_name = next(iter(names))
    aliases.discard(canonical_name)
    aliases.discard(code)
    polygons = [polygon for feature in features for polygon in feature.polygons]
    bounds: tuple[float, float, float, float] = (
        min(feature.bounds[0] for feature in features),
        max(feature.bounds[1] for feature in features),
        min(feature.bounds[2] for feature in features),
        max(feature.bounds[3] for feature in features),
    )
    label_latitude = sum(feature.label_latitude for feature in features) / len(features)
    label_longitude = sum(feature.label_longitude for feature in features) / len(
        features
    )
    alpha2 = next(iter(alpha2_values), None)
    timezone_name = _select_timezone(
        timezones.get(alpha2, ()) if alpha2 else (),
        latitude=label_latitude,
        longitude=label_longitude,
    )
    return _GeneratedCountry(
        code,
        canonical_name,
        sorted(aliases, key=lambda value: (value.casefold(), value)),
        timezone_name,
        (
            round(bounds[0], 6),
            round(bounds[1], 6),
            round(bounds[2], 6),
            round(bounds[3], 6),
        ),
        polygons,
    )


def _remove_ambiguous_aliases(countries: Sequence[_GeneratedCountry]) -> None:
    owners: dict[str, set[str]] = defaultdict(set)
    for country in countries:
        owners[country.canonical_name.casefold()].add(country.alpha3)
        owners[country.alpha3.casefold()].add(country.alpha3)
        for alias in country.aliases:
            owners[alias.casefold()].add(country.alpha3)
    for country in countries:
        country.aliases = [
            alias
            for alias in country.aliases
            if owners[alias.casefold()] == {country.alpha3}
        ]


def _geometry_polygons(geometry: Mapping[str, Any]) -> list[list[tuple[float, float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return []
    raw_polygons: list[object]
    if geometry_type == "Polygon":
        raw_polygons = [coordinates]
    elif geometry_type == "MultiPolygon":
        raw_polygons = coordinates
    else:
        return []
    polygons: list[list[tuple[float, float]]] = []
    for raw_polygon in raw_polygons:
        if not isinstance(raw_polygon, list) or not raw_polygon:
            continue
        exterior = raw_polygon[0]
        if not isinstance(exterior, list):
            continue
        points: list[tuple[float, float]] = []
        for raw_point in exterior:
            if not isinstance(raw_point, list) or len(raw_point) < 2:
                continue
            longitude, latitude = float(raw_point[0]), float(raw_point[1])
            if -180 <= longitude <= 180 and -90 <= latitude <= 90:
                points.append((latitude, longitude))
        simplified = _simplify_ring(points)
        if len(simplified) >= 3:
            polygons.append(simplified)
    return polygons


def _simplify_ring(
    points: Sequence[tuple[float, float]], tolerance: float = 0.02
) -> list[tuple[float, float]]:
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) <= 4:
        return [(round(lat, 6), round(lon, 6)) for lat, lon in points]
    selected = [points[0]]
    threshold = tolerance * tolerance
    for point in points[1:]:
        previous = selected[-1]
        if (point[0] - previous[0]) ** 2 + (point[1] - previous[1]) ** 2 >= threshold:
            selected.append(point)
    if len(selected) < 3:
        selected = list(points)
    return [(round(lat, 6), round(lon, 6)) for lat, lon in selected]


def _parse_tzdata(
    content: bytes,
) -> tuple[dict[str, tuple[_TimezoneChoice, ...]], str]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(content), mode="r:gz")
    except tarfile.TarError as error:
        raise ValueError("IANA tzdata archive is invalid.") from error
    with archive:
        version_member = next(
            (
                member
                for member in archive.getmembers()
                if member.name.endswith("version")
            ),
            None,
        )
        zone_member = next(
            (
                member
                for member in archive.getmembers()
                if member.name.endswith("zone.tab")
            ),
            None,
        )
        if version_member is None or zone_member is None:
            raise ValueError("IANA tzdata archive is missing version or zone.tab.")
        version_handle = archive.extractfile(version_member)
        zone_handle = archive.extractfile(zone_member)
        if version_handle is None or zone_handle is None:
            raise ValueError("IANA tzdata archive entries are unreadable.")
        version = version_handle.read().decode("ascii").strip()
        zone_text = zone_handle.read().decode("utf-8")
    if not re.fullmatch(r"\d{4}[a-z]", version):
        raise ValueError("IANA tzdata version is invalid.")
    choices: dict[str, list[_TimezoneChoice]] = defaultdict(list)
    for line in zone_text.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 3 or not _ALPHA2_CODE.fullmatch(fields[0]):
            continue
        coordinates = _parse_iso6709(fields[1])
        if coordinates is None:
            continue
        choices[fields[0]].append(
            _TimezoneChoice(fields[2], coordinates[0], coordinates[1])
        )
    if len(choices) < 200:
        raise ValueError("IANA tzdata did not provide expected country coverage.")
    return {key: tuple(value) for key, value in choices.items()}, version


def _parse_iso6709(value: str) -> tuple[float, float] | None:
    match = re.fullmatch(r"([+-])(\d{4}|\d{6})([+-])(\d{5}|\d{7})", value)
    if match is None:
        return None
    lat_sign, lat_value, lon_sign, lon_value = match.groups()
    latitude = _coordinate_value(lat_value, degree_digits=2)
    longitude = _coordinate_value(lon_value, degree_digits=3)
    if lat_sign == "-":
        latitude = -latitude
    if lon_sign == "-":
        longitude = -longitude
    return latitude, longitude


def _coordinate_value(value: str, *, degree_digits: int) -> float:
    degrees = int(value[:degree_digits])
    minutes = int(value[degree_digits : degree_digits + 2])
    seconds = int(value[degree_digits + 2 :]) if len(value) > degree_digits + 2 else 0
    return degrees + minutes / 60 + seconds / 3600


def _select_timezone(
    choices: Sequence[_TimezoneChoice], *, latitude: float, longitude: float
) -> str | None:
    if not choices:
        return None

    def distance(choice: _TimezoneChoice) -> float:
        longitude_delta = abs(choice.longitude - longitude)
        longitude_delta = min(longitude_delta, 360 - longitude_delta)
        return (choice.latitude - latitude) ** 2 + longitude_delta**2

    return min(choices, key=lambda choice: (distance(choice), choice.name)).name


def _validate_generated_payload(
    payload: Mapping[str, object], *, minimum_country_count: int
) -> None:
    _, countries = parse_country_catalog_payload(payload)
    if len(countries) < minimum_country_count:
        raise ValueError("Generated catalog is below the required country count.")
    codes_in_order = [country.alpha3_code for country in countries]
    if codes_in_order != sorted(codes_in_order):
        raise ValueError("Generated catalog is not deterministically ordered.")
    codes = set(codes_in_order)
    required = {"FRA", "JPN", "TUR", "USA", "VEN", "VNM"}
    if not required.issubset(codes):
        raise ValueError("Generated catalog is missing preservation countries.")
    polygon_coverage = sum(
        bool(country.geographic_area.polygons) for country in countries
    )
    timezone_coverage = sum(
        country.default_timezone is not None for country in countries
    )
    if polygon_coverage / len(countries) < 0.95:
        raise ValueError("Generated catalog polygon coverage is insufficient.")
    if timezone_coverage / len(countries) < 0.75:
        raise ValueError("Generated catalog timezone coverage is insufficient.")


def _source_versions(
    snapshot: CountryCatalogSourceSnapshot,
) -> tuple[CountryCatalogSourceVersion, ...]:
    natural_hash = hashlib.sha256(snapshot.natural_earth_bytes).hexdigest()
    timezone_hash = hashlib.sha256(snapshot.tzdata_bytes).hexdigest()
    _, timezone_version = _parse_tzdata(snapshot.tzdata_bytes)
    return (
        CountryCatalogSourceVersion(
            "natural-earth-admin-0",
            snapshot.natural_earth_version,
            snapshot.natural_earth_revision,
            f"sha256:{natural_hash}",
        ),
        CountryCatalogSourceVersion(
            "iana-tzdata",
            timezone_version,
            f"sha256:{timezone_hash}",
            f"sha256:{timezone_hash}",
        ),
    )


def _serialize_status(status: CountryCatalogUpdateStatus) -> dict[str, object]:
    return {
        "state": status.state.value,
        "trigger": status.trigger.value if status.trigger else None,
        "active_version": status.active_version,
        "country_count": status.country_count,
        "last_attempt_at": _datetime_text(status.last_attempt_at),
        "last_success_at": _datetime_text(status.last_success_at),
        "message": status.message,
        "failure_code": status.failure_code,
        "sources": [
            {
                "source_id": source.source_id,
                "version": source.version,
                "revision": source.revision,
                "sha256": source.sha256,
            }
            for source in status.sources
        ],
    }


def _deserialize_status(
    payload: Mapping[str, Any] | None,
    *,
    catalog: StaticCountryCatalog,
    automatic_updates_enabled: bool,
) -> CountryCatalogUpdateStatus:
    metadata = catalog.metadata
    active_version = str(metadata.get("version", "unknown"))
    country_count = len(catalog.countries())
    if payload is None:
        return CountryCatalogUpdateStatus(
            CountryCatalogUpdateState.NEVER_RUN,
            active_version,
            country_count,
            automatic_updates_enabled,
        )
    try:
        state = CountryCatalogUpdateState(str(payload.get("state")))
        trigger_value = payload.get("trigger")
        trigger = (
            CountryCatalogUpdateTrigger(str(trigger_value))
            if trigger_value is not None
            else None
        )
        source_payloads = payload.get("sources", [])
        if not isinstance(source_payloads, list):
            raise ValueError("Invalid stored source status.")
        sources = tuple(
            CountryCatalogSourceVersion(
                _required_string(_json_object(item), "source_id"),
                _required_string(_json_object(item), "version"),
                _required_string(_json_object(item), "revision"),
                _required_string(_json_object(item), "sha256"),
            )
            for item in source_payloads
        )
        return CountryCatalogUpdateStatus(
            state=state,
            active_version=active_version,
            country_count=country_count,
            automatic_updates_enabled=automatic_updates_enabled,
            trigger=trigger,
            last_attempt_at=_parse_datetime(payload.get("last_attempt_at")),
            last_success_at=_parse_datetime(payload.get("last_success_at")),
            message=str(
                payload.get("message") or "Country catalog status is available."
            ),
            failure_code=(
                str(payload["failure_code"])
                if payload.get("failure_code") is not None
                else None
            ),
            sources=sources,
        )
    except (TypeError, ValueError, KeyError):
        return CountryCatalogUpdateStatus(
            state=CountryCatalogUpdateState.FAILED,
            active_version=active_version,
            country_count=country_count,
            automatic_updates_enabled=automatic_updates_enabled,
            message=(
                "Stored update status was invalid; the active country catalog was "
                "retained."
            ),
            failure_code="invalid_status",
        )


def _replace_status(
    status: CountryCatalogUpdateStatus, **changes: object
) -> CountryCatalogUpdateStatus:
    values: dict[str, object] = {
        "state": status.state,
        "active_version": status.active_version,
        "country_count": status.country_count,
        "automatic_updates_enabled": status.automatic_updates_enabled,
        "trigger": status.trigger,
        "last_attempt_at": status.last_attempt_at,
        "last_success_at": status.last_success_at,
        "next_scheduled_at": status.next_scheduled_at,
        "message": status.message,
        "failure_code": status.failure_code,
        "sources": status.sources,
    }
    values.update(changes)
    return CountryCatalogUpdateStatus(**cast(Any, values))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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


def _property_code(
    properties: Mapping[str, Any], keys: Sequence[str], pattern: re.Pattern[str]
) -> str | None:
    for key in keys:
        value = properties.get(key)
        if isinstance(value, str):
            normalized = value.strip().upper()
            if pattern.fullmatch(normalized):
                return normalized
    return None


def _first_property(properties: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = properties.get(key)
        if isinstance(value, str) and _usable_alias(value):
            return value.strip()
    return None


def _alias_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(
        item.strip() for item in re.split(r"[|;]", value) if _usable_alias(item)
    )


def _usable_alias(value: str) -> bool:
    normalized = value.strip()
    if not 2 <= len(normalized) <= 120 or normalized in {"-99", "null", "Null"}:
        return False
    if normalized.upper() in _SHORT_ALIAS_STOPLIST:
        return False
    return any(character.isalpha() for character in normalized)


def _float_property(value: object, default: float) -> float:
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError):
        return default
    return result


def _failure_code(error: Exception) -> str:
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return "upstream_timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return "upstream_http_error"
    if isinstance(error, ValueError):
        return "validation_failed"
    if isinstance(error, OSError):
        return "storage_failure"
    return "update_failed"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Country catalog automation requires timezone-aware time.")
    return value.astimezone(UTC)


def _datetime_text(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Stored catalog update time is invalid.")
    parsed = datetime.fromisoformat(value)
    return _aware_utc(parsed)


def _next_month(month_start: datetime) -> datetime:
    if month_start.month == 12:
        return month_start.replace(year=month_start.year + 1, month=1)
    return month_start.replace(month=month_start.month + 1)
