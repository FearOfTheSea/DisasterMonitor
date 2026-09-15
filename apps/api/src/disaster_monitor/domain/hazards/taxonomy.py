"""Extensible hazard definitions and warning-to-hazard admission policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from disaster_monitor.domain.disaster_types import Disaster


class HazardIdentityKind(StrEnum):
    DISCRETE_EVENT = "discrete_event"
    TRACKED_SYSTEM = "tracked_system"
    SPATIAL_TIME_WINDOW = "spatial_time_window"


@dataclass(frozen=True, slots=True)
class HazardDefinition:
    hazard_id: str
    display_name: str
    aliases: tuple[str, ...]
    identity_kind: HazardIdentityKind
    disaster: Disaster | None
    warning_event_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.hazard_id.strip() or not self.display_name.strip():
            raise ValueError("A hazard definition requires stable identity and a name.")
        if self.hazard_id != self.hazard_id.casefold():
            raise ValueError("Hazard identifiers must be lowercase.")
        if not self.aliases:
            raise ValueError("A hazard definition requires at least one alias.")


class HazardTaxonomy:
    def __init__(self, definitions: tuple[HazardDefinition, ...]) -> None:
        if not definitions:
            raise ValueError("A hazard taxonomy cannot be empty.")
        by_id = {item.hazard_id: item for item in definitions}
        if len(by_id) != len(definitions):
            raise ValueError("Hazard identifiers must be unique.")
        aliases: dict[str, HazardDefinition] = {}
        for definition in definitions:
            for alias in (definition.hazard_id, *definition.aliases):
                normalized = alias.strip().casefold()
                existing = aliases.get(normalized)
                if existing is not None and existing != definition:
                    raise ValueError(f"Hazard alias {alias!r} is ambiguous.")
                aliases[normalized] = definition
        self._definitions = definitions
        self._by_id = by_id
        self._aliases = aliases

    def require(self, hazard_id: str) -> HazardDefinition:
        try:
            return self._by_id[hazard_id.strip().casefold()]
        except KeyError as error:
            raise KeyError(f"Unknown hazard: {hazard_id}") from error

    def resolve(self, value: str) -> HazardDefinition:
        normalized = value.strip().casefold()
        direct = self._aliases.get(normalized)
        if direct is not None:
            return direct
        matches = {
            definition
            for alias, definition in self._aliases.items()
            if alias and alias in normalized
        }
        if len(matches) != 1:
            raise KeyError(f"Hazard text did not resolve uniquely: {value}")
        return matches.pop()

    def physical_hazards(self) -> tuple[HazardDefinition, ...]:
        return tuple(item for item in self._definitions if item.disaster is not None)

    def physical_disaster_for_warning(self, event: str) -> Disaster | None:
        normalized = event.strip().casefold()
        matches = {
            definition.disaster
            for definition in self._definitions
            if definition.disaster is not None
            and any(
                code.casefold() in normalized for code in definition.warning_event_codes
            )
        }
        return matches.pop() if len(matches) == 1 else None


def _definition(
    disaster: Disaster,
    display_name: str,
    aliases: tuple[str, ...],
    *,
    identity: HazardIdentityKind = HazardIdentityKind.DISCRETE_EVENT,
    warning_codes: tuple[str, ...] = (),
) -> HazardDefinition:
    return HazardDefinition(
        hazard_id=disaster.value,
        display_name=display_name,
        aliases=aliases,
        identity_kind=identity,
        disaster=disaster,
        warning_event_codes=warning_codes,
    )


DEFAULT_HAZARD_TAXONOMY = HazardTaxonomy(
    (
        _definition(
            Disaster.EARTHQUAKE,
            "Earthquake",
            ("earthquake", "quake", "seismic event"),
            warning_codes=("earthquake",),
        ),
        _definition(
            Disaster.FLOOD,
            "Flood",
            ("flood", "river flooding", "flash flood"),
            warning_codes=("flood",),
        ),
        _definition(
            Disaster.WILDFIRE,
            "Wildfire",
            ("wildfire", "forest fire", "bushfire"),
            warning_codes=("wildfire", "fire weather"),
        ),
        _definition(
            Disaster.LANDSLIDE,
            "Landslide",
            ("landslide", "mudslide", "debris flow"),
            warning_codes=("landslide",),
        ),
        _definition(
            Disaster.TROPICAL_CYCLONE,
            "Tropical cyclone",
            ("tropical cyclone", "hurricane", "typhoon"),
            identity=HazardIdentityKind.TRACKED_SYSTEM,
            warning_codes=("hurricane", "tropical storm", "typhoon", "cyclone"),
        ),
        _definition(
            Disaster.VOLCANIC_ERUPTION,
            "Volcanic eruption",
            ("volcanic eruption", "volcano eruption"),
            warning_codes=("volcano", "volcanic"),
        ),
        _definition(
            Disaster.DROUGHT,
            "Drought",
            ("drought", "dry spell", "khô hạn"),
            identity=HazardIdentityKind.SPATIAL_TIME_WINDOW,
            warning_codes=("drought",),
        ),
        HazardDefinition(
            hazard_id="tsunami_warning",
            display_name="Tsunami warning",
            aliases=("tsunami", "tsunami warning"),
            identity_kind=HazardIdentityKind.TRACKED_SYSTEM,
            disaster=None,
            warning_event_codes=("tsunami",),
        ),
    )
)


__all__ = [
    "DEFAULT_HAZARD_TAXONOMY",
    "HazardDefinition",
    "HazardIdentityKind",
    "HazardTaxonomy",
]
