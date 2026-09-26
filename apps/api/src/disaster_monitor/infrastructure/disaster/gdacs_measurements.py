"""Typed, bounded measurements from GDACS event-list properties."""

from math import isfinite

from disaster_monitor.domain.disaster import (
    EventMeasurement,
    MeasurementKind,
    SourceReference,
)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def alert_measurements(
    properties: dict[object, object], source: SourceReference
) -> tuple[EventMeasurement, ...]:
    alert = properties.get("alertlevel")
    value = alert.strip() if isinstance(alert, str) else ""
    return (
        (EventMeasurement(MeasurementKind.SEVERITY, value, source=source),)
        if value
        else ()
    )


def earthquake_measurements(
    properties: dict[object, object], source: SourceReference
) -> tuple[EventMeasurement, ...]:
    measurements = list(alert_measurements(properties, source))
    severity_data = properties.get("severitydata")
    magnitude = (
        _number(severity_data.get("severity"))
        if isinstance(severity_data, dict)
        else None
    )
    if magnitude is not None:
        measurements.append(
            EventMeasurement(MeasurementKind.MAGNITUDE, magnitude, source=source)
        )
    return tuple(measurements)


def cyclone_measurements(
    properties: dict[object, object], source: SourceReference
) -> tuple[EventMeasurement, ...]:
    measurements = list(alert_measurements(properties, source))
    severity_data = properties.get("severitydata")
    if isinstance(severity_data, dict):
        wind_speed = _number(severity_data.get("severity"))
        if (
            wind_speed is not None
            and 0 < wind_speed <= 450
            and severity_data.get("severityunit") == "km/h"
        ):
            measurements.append(
                EventMeasurement(
                    MeasurementKind.MAXIMUM_WIND_SPEED,
                    round(wind_speed),
                    unit="km/h",
                    source=source,
                )
            )
    return tuple(measurements)
