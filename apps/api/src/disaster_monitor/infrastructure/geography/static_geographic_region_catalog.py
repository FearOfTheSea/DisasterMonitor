"""Versioned local catalog of provenanced named-region country associations."""

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import cast
from urllib.parse import urlparse

from disaster_monitor.application.ports.geographic_regions import (
    GeographicRegionCountryMatch,
)


@dataclass(frozen=True, slots=True)
class _Region:
    name: str
    aliases: tuple[str, ...]
    country_code: str
    source_url: str


class StaticGeographicRegionCatalog:
    def __init__(self) -> None:
        resource = files(
            "disaster_monitor.infrastructure.geography.resources"
        ).joinpath("geographic_region_countries.v1.json")
        payload = cast(
            dict[str, object], json.loads(resource.read_text(encoding="utf-8"))
        )
        self._regions = _parse_regions(payload)
        terms = tuple(
            sorted(
                (
                    (term, region)
                    for region in self._regions
                    for term in (region.name, *region.aliases)
                ),
                key=lambda item: (-len(item[0]), item[0].casefold()),
            )
        )
        self._patterns = tuple(
            (
                re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE),
                term,
                region,
            )
            for term, region in terms
        )

    def find(self, text: str) -> GeographicRegionCountryMatch | None:
        matches = tuple(
            (match.start(), -len(term), term.casefold(), term, region)
            for pattern, term, region in self._patterns
            if (match := pattern.search(text)) is not None
        )
        if not matches:
            return None
        _, _, _, term, region = min(matches)
        return GeographicRegionCountryMatch(
            matched_name=term,
            country_code=region.country_code,
            source_url=region.source_url,
        )


def _parse_regions(payload: dict[str, object]) -> tuple[_Region, ...]:
    raw_regions = payload.get("regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise ValueError("Geographic region catalog requires region records.")
    regions: list[_Region] = []
    owners: dict[str, str] = {}
    for raw_region in raw_regions:
        if not isinstance(raw_region, dict):
            raise ValueError("Geographic region records must be objects.")
        name = _required_text(raw_region, "name")
        country_code = _required_text(raw_region, "country_code").upper()
        source_url = _required_text(raw_region, "source_url")
        raw_aliases = raw_region.get("aliases", [])
        if not re.fullmatch(r"[A-Z]{3}", country_code):
            raise ValueError(f"Region {name} has an invalid country code.")
        parsed_url = urlparse(source_url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            raise ValueError(f"Region {name} requires an HTTPS source URL.")
        if not isinstance(raw_aliases, list):
            raise ValueError(f"Region {name} aliases must be a list.")
        aliases = tuple(
            dict.fromkeys(
                alias
                for value in raw_aliases
                if (alias := str(value).strip()) and alias.casefold() != name.casefold()
            )
        )
        for term in (name, *aliases):
            owner = owners.setdefault(term.casefold(), country_code)
            if owner != country_code:
                raise ValueError(
                    f"Region alias {term} has ambiguous country ownership."
                )
        regions.append(_Region(name, aliases, country_code, source_url))
    return tuple(regions)


def _required_text(item: dict[object, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Geographic region record requires {key}.")
    return value.strip()
