"""Packaged deterministic country catalog with atomic runtime refresh."""

import json
import re
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from threading import RLock
from typing import Any, cast

from disaster_monitor.domain.disaster import (
    BoundaryValidationQuality,
    Country,
    GeographicArea,
)


class StaticCountryCatalog:
    """Resolve aliases from packaged or atomically promoted versioned metadata."""

    def __init__(self, catalog_root: Path | None = None) -> None:
        self._active_path = catalog_root / "active.json" if catalog_root else None
        self._active_mtime_ns: int | None = None
        self._lock = RLock()
        resource = files(
            "disaster_monitor.infrastructure.geography.resources"
        ).joinpath("countries.v1.json")
        payload = cast(
            dict[str, object], json.loads(resource.read_text(encoding="utf-8"))
        )
        if self._active_path is not None and self._active_path.is_file():
            try:
                candidate = cast(
                    dict[str, object],
                    json.loads(self._active_path.read_text(encoding="utf-8")),
                )
                parse_country_catalog_payload(candidate)
                payload = candidate
                self._active_mtime_ns = self._active_path.stat().st_mtime_ns
            except (OSError, ValueError, TypeError, KeyError):
                self._active_mtime_ns = None
        self.activate_payload(payload)

    def activate_payload(self, payload: Mapping[str, object]) -> None:
        """Replace in-memory indexes only after complete payload validation."""
        metadata, countries = parse_country_catalog_payload(payload)
        term_countries: dict[str, tuple[Country, ...]] = {}
        for country in countries:
            for term in (
                country.canonical_name,
                country.alpha3_code,
                *country.aliases,
            ):
                key = term.casefold()
                existing = term_countries.get(key, ())
                if all(item.alpha3_code != country.alpha3_code for item in existing):
                    term_countries[key] = (*existing, country)
        ordered_terms = sorted(term_countries, key=lambda value: (-len(value), value))
        mention_pattern = (
            re.compile(
                r"(?<!\w)(?:"
                + "|".join(re.escape(term) for term in ordered_terms)
                + r")(?!\w)",
                re.I,
            )
            if ordered_terms
            else None
        )
        with self._lock:
            self.metadata = metadata
            self._countries = countries
            self._by_code = {
                country.alpha3_code: country for country in self._countries
            }
            self._term_countries = term_countries
            self._mention_pattern = mention_pattern

    def _refresh_if_changed(self) -> None:
        path = self._active_path
        if path is None or not path.is_file():
            return
        try:
            mtime_ns = path.stat().st_mtime_ns
            if mtime_ns == self._active_mtime_ns:
                return
            payload = cast(
                dict[str, object], json.loads(path.read_text(encoding="utf-8"))
            )
            self.activate_payload(payload)
            self._active_mtime_ns = mtime_ns
        except (OSError, ValueError, TypeError, KeyError):
            return

    def mark_active_path_current(self) -> None:
        """Record the active file revision after an in-process promotion."""
        if self._active_path is not None and self._active_path.is_file():
            self._active_mtime_ns = self._active_path.stat().st_mtime_ns

    def countries(self) -> tuple[Country, ...]:
        self._refresh_if_changed()
        with self._lock:
            return self._countries

    def find_mentions(self, text: str) -> tuple[Country, ...]:
        self._refresh_if_changed()
        with self._lock:
            pattern = self._mention_pattern
            term_countries = self._term_countries
        if pattern is None:
            return ()
        found: list[Country] = []
        found_codes: set[str] = set()
        for match in pattern.finditer(text):
            for country in term_countries.get(match.group(0).casefold(), ()):
                if country.alpha3_code not in found_codes:
                    found.append(country)
                    found_codes.add(country.alpha3_code)
        return tuple(found)

    def get_by_alpha3(self, alpha3_code: str) -> Country | None:
        self._refresh_if_changed()
        with self._lock:
            return self._by_code.get(alpha3_code.upper())

    def contains(self, country: Country, latitude: float, longitude: float) -> bool:
        return country.geographic_area.contains(latitude, longitude)


def parse_country_catalog_payload(
    payload: Mapping[str, object],
) -> tuple[dict[str, object], tuple[Country, ...]]:
    """Validate and translate serialized catalog data without partial activation."""
    metadata = _mapping(payload.get("metadata"), "metadata")
    raw_countries = payload.get("countries")
    if not isinstance(raw_countries, list) or not raw_countries:
        raise ValueError("Country catalog requires a non-empty countries list.")
    countries = tuple(_country(_mapping(item, "country")) for item in raw_countries)
    codes = [country.alpha3_code for country in countries]
    if len(set(codes)) != len(codes):
        raise ValueError("Country catalog alpha-3 codes must be unique.")
    return dict(metadata), countries


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Country catalog {label} must be an object.")
    return cast(Mapping[str, Any], value)


def _country(item: Mapping[str, Any]) -> Country:
    code = str(item.get("alpha3", "")).strip().upper()
    name = str(item.get("name", "")).strip()
    if not re.fullmatch(r"[A-Z]{3}", code) or not name:
        raise ValueError("Country catalog entries require alpha-3 code and name.")
    aliases_value = item.get("aliases", [])
    bounds_value = item.get("bounds")
    polygons_value = item.get("polygons", [])
    if not isinstance(aliases_value, list) or not isinstance(bounds_value, list):
        raise ValueError(f"Country catalog entry {code} has invalid metadata.")
    if len(bounds_value) != 4 or not isinstance(polygons_value, list):
        raise ValueError(f"Country catalog entry {code} has invalid geometry.")
    bounds = tuple(float(value) for value in bounds_value)
    if not (
        -90 <= bounds[0] <= bounds[1] <= 90 and -180 <= bounds[2] <= bounds[3] <= 180
    ):
        raise ValueError(f"Country catalog entry {code} has invalid bounds.")
    polygons = tuple(
        tuple((float(point[0]), float(point[1])) for point in polygon)
        for polygon in polygons_value
        if isinstance(polygon, list)
    )
    if any(
        len(polygon) < 3
        or any(
            not (-90 <= latitude <= 90 and -180 <= longitude <= 180)
            for latitude, longitude in polygon
        )
        for polygon in polygons
    ):
        raise ValueError(f"Country catalog entry {code} has invalid polygons.")
    aliases = tuple(
        dict.fromkeys(
            alias
            for value in aliases_value
            if (alias := str(value).strip())
            and alias.casefold() not in {code.casefold(), name.casefold()}
        )
    )
    timezone_value = item.get("timezone")
    timezone_name = str(timezone_value).strip() if timezone_value is not None else None
    return Country(
        alpha3_code=code,
        canonical_name=name,
        aliases=aliases,
        default_timezone=timezone_name or None,
        geographic_area=GeographicArea(
            min_latitude=bounds[0],
            max_latitude=bounds[1],
            min_longitude=bounds[2],
            max_longitude=bounds[3],
            validation_quality=(
                BoundaryValidationQuality.POLYGON
                if polygons
                else BoundaryValidationQuality.BOUNDING_BOX
            ),
            polygons=polygons,
        ),
    )
