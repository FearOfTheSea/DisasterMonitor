"""Autonomous, fail-closed generation and promotion of global country metadata."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from disaster_monitor.application.ports.geography import (
    CountryCatalogSourceVersion,
)
from disaster_monitor.infrastructure.geography.country_catalog_source import (
    CountryCatalogSourceSnapshot,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    parse_country_catalog_payload,
)

_COUNTRY_CODE = re.compile(r"[A-Z]{3}")
_ALPHA2_CODE = re.compile(r"[A-Z]{2}")
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
