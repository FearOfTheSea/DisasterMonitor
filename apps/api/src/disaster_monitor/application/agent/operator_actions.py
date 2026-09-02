"""Bounded operator-action vocabulary and deterministic application policy."""

from dataclasses import dataclass
from enum import StrEnum

from disaster_monitor.application.agent.models import ValidatedDisasterTask
from disaster_monitor.application.disaster import GeographicScope
from disaster_monitor.domain.disaster import Disaster, IncidentWatchScope

MAX_OPERATOR_ACTIONS = 4


class OperatorActionRisk(StrEnum):
    AUTOMATIC = "automatic"
    CONFIRMATION_REQUIRED = "confirmation_required"


class OperatorActionType(StrEnum):
    OPEN_PANEL = "open_panel"
    SET_TIME_WINDOW = "set_time_window"
    SHOW_LAYER = "show_layer"
    CREATE_INCIDENT_WATCH = "create_incident_watch"


class OperatorActionOperation(StrEnum):
    OPEN = "open"
    SET = "set"
    SHOW = "show"


class OperatorActionTarget(StrEnum):
    PANEL = "panel"
    TIME_WINDOW = "time_window"
    MAP_LAYER = "map_layer"


@dataclass(frozen=True, slots=True)
class AutomaticOperatorAction:
    action_id: str
    action_type: OperatorActionType
    risk: OperatorActionRisk
    operation: OperatorActionOperation
    target: OperatorActionTarget
    value: str
    user_safe_label: str


@dataclass(frozen=True, slots=True)
class IncidentWatchOperatorAction:
    action_id: str
    action_type: OperatorActionType
    risk: OperatorActionRisk
    disaster: Disaster
    scope: IncidentWatchScope
    refresh_interval_seconds: int
    user_safe_label: str


OperatorAction = AutomaticOperatorAction | IncidentWatchOperatorAction


_NAVIGATION_ACTIONS = {
    "open:findings": ("findings", "Open Findings"),
    "open:sources": ("sources", "Open Source Catalog"),
    "open:watches": ("watches", "Open Incident Watches"),
    "open:operations": ("operations", "Open Evidence Operations"),
}
_TIME_ACTIONS = {
    "time:1h": "1h",
    "time:6h": "6h",
    "time:24h": "24h",
    "time:48h": "48h",
    "time:7d": "7d",
}
_LAYER_IDS = (
    "active-incidents",
    "satellite-imagery",
    "cop-evidence",
    "cyclone-supplemental",
    "authoritative-weather-alerts",
    "compound-correlations",
)
_WATCH_INTERVALS = {
    900: "15-minute",
    1800: "30-minute",
    3600: "1-hour",
    21600: "6-hour",
    86400: "24-hour",
}

OPERATOR_ACTION_IDS = frozenset(
    {
        *_NAVIGATION_ACTIONS,
        *_TIME_ACTIONS,
        *(f"show-layer:{layer_id}" for layer_id in _LAYER_IDS),
        *(f"create-watch:{interval}" for interval in _WATCH_INTERVALS),
    }
)


def validate_operator_action_candidates(value: object) -> tuple[str, ...]:
    """Return candidates only when the complete model selection is safe."""
    if not isinstance(value, (tuple, list)):
        return ()
    if len(value) > MAX_OPERATOR_ACTIONS:
        return ()
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > 100
        for item in value
    ):
        return ()
    candidates = tuple(item.strip() for item in value)
    if len(set(candidates)) != len(candidates):
        return ()
    if any(candidate not in OPERATOR_ACTION_IDS for candidate in candidates):
        return ()
    return candidates


def resolve_operator_actions(
    task: ValidatedDisasterTask,
) -> tuple[OperatorAction, ...]:
    """Resolve exact IDs using only validated task metadata and this policy."""
    candidates = validate_operator_action_candidates(task.operator_action_ids)
    actions: list[OperatorAction] = []
    for action_id in candidates:
        if action_id in _NAVIGATION_ACTIONS:
            value, label = _NAVIGATION_ACTIONS[action_id]
            actions.append(
                AutomaticOperatorAction(
                    action_id=action_id,
                    action_type=OperatorActionType.OPEN_PANEL,
                    risk=OperatorActionRisk.AUTOMATIC,
                    operation=OperatorActionOperation.OPEN,
                    target=OperatorActionTarget.PANEL,
                    value=value,
                    user_safe_label=label,
                )
            )
            continue
        if action_id in _TIME_ACTIONS:
            value = _TIME_ACTIONS[action_id]
            actions.append(
                AutomaticOperatorAction(
                    action_id=action_id,
                    action_type=OperatorActionType.SET_TIME_WINDOW,
                    risk=OperatorActionRisk.AUTOMATIC,
                    operation=OperatorActionOperation.SET,
                    target=OperatorActionTarget.TIME_WINDOW,
                    value=value,
                    user_safe_label=f"Show a {_time_label(value)} display window",
                )
            )
            continue
        if action_id.startswith("show-layer:"):
            layer_id = action_id.removeprefix("show-layer:")
            actions.append(
                AutomaticOperatorAction(
                    action_id=action_id,
                    action_type=OperatorActionType.SHOW_LAYER,
                    risk=OperatorActionRisk.AUTOMATIC,
                    operation=OperatorActionOperation.SHOW,
                    target=OperatorActionTarget.MAP_LAYER,
                    value=layer_id,
                    user_safe_label=f"Show {_layer_label(layer_id)}",
                )
            )
            continue
        watch_action = _resolve_watch_action(action_id, task)
        if watch_action is not None:
            actions.append(watch_action)
    return tuple(actions)


def _resolve_watch_action(
    action_id: str,
    task: ValidatedDisasterTask,
) -> IncidentWatchOperatorAction | None:
    if not action_id.startswith("create-watch:") or not isinstance(
        task.disaster, Disaster
    ):
        return None
    try:
        interval = int(action_id.removeprefix("create-watch:"))
    except ValueError:
        return None
    if interval not in _WATCH_INTERVALS:
        return None
    if task.geographic_scope is GeographicScope.WORLDWIDE:
        if task.country is not None:
            return None
        scope = IncidentWatchScope.worldwide()
        scope_label = "worldwide"
    elif task.geographic_scope is GeographicScope.COUNTRY and task.country is not None:
        scope = IncidentWatchScope.country(
            task.country.alpha3_code, task.country.canonical_name
        )
        scope_label = task.country.canonical_name
    else:
        return None
    return IncidentWatchOperatorAction(
        action_id=action_id,
        action_type=OperatorActionType.CREATE_INCIDENT_WATCH,
        risk=OperatorActionRisk.CONFIRMATION_REQUIRED,
        disaster=task.disaster,
        scope=scope,
        refresh_interval_seconds=interval,
        user_safe_label=(
            f"Create a {_WATCH_INTERVALS[interval]} {task.disaster.value} watch "
            f"for {scope_label}"
        ),
    )


def _time_label(value: str) -> str:
    return {
        "1h": "1-hour",
        "6h": "6-hour",
        "24h": "24-hour",
        "48h": "48-hour",
        "7d": "7-day",
    }[value]


def _layer_label(layer_id: str) -> str:
    return {
        "active-incidents": "Active incidents",
        "satellite-imagery": "Satellite imagery",
        "cop-evidence": "COP evidence",
        "cyclone-supplemental": "Cyclone supplemental geometry",
        "authoritative-weather-alerts": "Authoritative weather alerts",
        "compound-correlations": "Compound-hazard correlations",
    }[layer_id]
