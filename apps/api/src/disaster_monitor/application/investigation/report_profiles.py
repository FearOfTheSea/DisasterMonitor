"""Disaster-specific deterministic report section profiles."""

from dataclasses import dataclass

from disaster_monitor.domain.disaster import Disaster


@dataclass(frozen=True, slots=True)
class ReportProfile:
    """Section categories and honest missing-evidence language."""

    human_categories: frozenset[str]
    physical_categories: frozenset[str]
    response_categories: frozenset[str]
    secondary_title: str | None = None
    secondary_categories: frozenset[str] = frozenset()
    secondary_missing: str | None = None
    point_location_caveat: str | None = None


_HUMAN = frozenset(
    {"fatalities", "injuries", "missing", "rescued", "evacuations", "shelters"}
)
_PHYSICAL = frozenset(
    {
        "buildings",
        "buildings_destroyed",
        "buildings_damaged",
        "roads",
        "rail",
        "airports",
        "ports",
        "utilities",
        "infrastructure",
        "communications",
        "critical_facilities",
        "damage_status",
    }
)
_RESPONSE = frozenset(
    {"response", "government_response", "emergency_response", "rescue_operations"}
)

GENERIC_REPORT_PROFILE = ReportProfile(_HUMAN, _PHYSICAL, _RESPONSE)
FLOOD_REPORT_PROFILE = ReportProfile(
    _HUMAN,
    _PHYSICAL,
    _RESPONSE,
    point_location_caveat=(
        "The event-list point is a locator, not a satellite-observed flood extent "
        "or official boundary"
    ),
)
EARTHQUAKE_REPORT_PROFILE = ReportProfile(
    _HUMAN,
    _PHYSICAL | {"fires", "landslides"},
    _RESPONSE,
    secondary_title="Secondary impacts",
    secondary_categories=frozenset({"fires", "landslides"}),
    secondary_missing=(
        "No verified fire or landslide impact was found in the retrieved "
        "reports. A warning or advisory alone would not establish damage."
    ),
)
VOLCANIC_ERUPTION_REPORT_PROFILE = ReportProfile(
    _HUMAN,
    _PHYSICAL,
    _RESPONSE,
    secondary_title="Ash and eruption observations",
    secondary_categories=frozenset({"ash_observation"}),
    secondary_missing="No source-backed ash observation was retrieved for this event.",
)


def report_profile_for(disaster: Disaster) -> ReportProfile:
    """Return a dedicated profile or the conservative generic profile."""
    if disaster == Disaster.EARTHQUAKE:
        return EARTHQUAKE_REPORT_PROFILE
    if disaster == Disaster.FLOOD:
        return FLOOD_REPORT_PROFILE
    if disaster == Disaster.VOLCANIC_ERUPTION:
        return VOLCANIC_ERUPTION_REPORT_PROFILE
    return GENERIC_REPORT_PROFILE
