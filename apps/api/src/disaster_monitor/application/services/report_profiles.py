"""Hazard-specific deterministic report section profiles."""

from dataclasses import dataclass

from disaster_monitor.domain.disaster import Hazard


@dataclass(frozen=True, slots=True)
class ReportProfile:
    """Section categories and honest missing-evidence language."""

    human_categories: frozenset[str]
    physical_categories: frozenset[str]
    response_categories: frozenset[str]
    secondary_title: str | None = None
    secondary_categories: frozenset[str] = frozenset()
    secondary_missing: str | None = None


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
_RESPONSE = frozenset({"response", "government_response", "emergency_response"})

GENERIC_REPORT_PROFILE = ReportProfile(_HUMAN, _PHYSICAL, _RESPONSE)
EARTHQUAKE_REPORT_PROFILE = ReportProfile(
    _HUMAN,
    _PHYSICAL | {"fires", "landslides"},
    _RESPONSE,
    secondary_title="Tsunami and secondary hazards",
    secondary_categories=frozenset({"tsunami", "fires", "landslides"}),
    secondary_missing=(
        "No verified tsunami, fire, or landslide impact was found in the retrieved "
        "reports. A warning or advisory alone would not establish damage."
    ),
)


def report_profile_for(hazard: Hazard) -> ReportProfile:
    """Return a dedicated profile or the conservative generic profile."""
    if hazard == Hazard.EARTHQUAKE:
        return EARTHQUAKE_REPORT_PROFILE
    return GENERIC_REPORT_PROFILE
