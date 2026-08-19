"""Registry-bound validation for normalized provider evidence."""

from datetime import datetime
from math import isfinite
from urllib.parse import urlsplit

from disaster_monitor.application.disaster import (
    DisasterQuery,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventGeometry,
    EventGeometryKind,
    EventMeasurement,
    FactStatus,
    MeasurementKind,
    PhysicalEventIdentity,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)


class SourceEvidencePolicyError(ValueError):
    """A normalized record escaped its approved source boundary."""


def validate_event_evidence(
    record: object,
    query: DisasterQuery,
    *,
    source_id: str,
    allowed_hosts: frozenset[str],
) -> DisasterEvent:
    if not isinstance(record, DisasterEvent):
        raise SourceEvidencePolicyError(
            "The event provider returned a wrong record type."
        )
    _validate_source(record.source, source_id=source_id, allowed_hosts=allowed_hosts)
    if not isinstance(record.country, Country):
        raise SourceEvidencePolicyError("The event country is invalid.")
    if not isinstance(record.disaster, Disaster) or record.disaster != query.disaster:
        raise SourceEvidencePolicyError(
            "The event disaster is outside the selected scope."
        )
    if record.country.alpha3_code != query.country.alpha3_code:
        raise SourceEvidencePolicyError(
            "The event country is outside the selected scope."
        )
    if (
        not isinstance(record.event_id, str)
        or not record.event_id.strip()
        or not isinstance(record.location, str)
        or not record.location.strip()
        or not _aware(record.event_time)
    ):
        raise SourceEvidencePolicyError("The event identity or time is invalid.")
    _validate_geometry(record.geometry, record.source)
    _validate_measurements(record.measurements, record.source)
    return record


def validate_worldwide_event_evidence(
    record: object,
    query: WorldwideDisasterQuery,
    *,
    source_id: str,
    allowed_hosts: frozenset[str],
) -> WorldwideDisasterEvent:
    """Validate an event whose admitted query scope is explicitly worldwide."""
    if not isinstance(record, WorldwideDisasterEvent):
        raise SourceEvidencePolicyError(
            "The worldwide event provider returned a wrong record type."
        )
    _validate_source(record.source, source_id=source_id, allowed_hosts=allowed_hosts)
    if record.disaster != query.disaster:
        raise SourceEvidencePolicyError(
            "The worldwide event disaster is outside the selected scope."
        )
    if (
        not isinstance(record.event_id, str)
        or not record.event_id.strip()
        or not isinstance(record.location, str)
        or not record.location.strip()
        or not _aware(record.event_time)
    ):
        raise SourceEvidencePolicyError(
            "The worldwide event identity or time is invalid."
        )
    _validate_geometry(record.geometry, record.source)
    _validate_measurements(record.measurements, record.source)
    return record


def validate_situation_evidence(
    record: object,
    query: DisasterQuery,
    *,
    source_id: str,
    allowed_hosts: frozenset[str],
) -> SituationReport:
    if not isinstance(record, SituationReport):
        raise SourceEvidencePolicyError(
            "The situation provider returned a wrong record type."
        )
    _validate_source(record.source, source_id=source_id, allowed_hosts=allowed_hosts)
    if not isinstance(record.narrative, str):
        raise SourceEvidencePolicyError("The situation narrative is invalid.")
    if not isinstance(record.facts, tuple):
        raise SourceEvidencePolicyError("The situation fact collection is invalid.")
    _validate_measurements(record.measurements, record.source)
    if record.disaster is not None and (
        not isinstance(record.disaster, Disaster) or record.disaster != query.disaster
    ):
        raise SourceEvidencePolicyError(
            "The situation disaster is outside the selected scope."
        )
    if not isinstance(record.country_codes, tuple) or any(
        not isinstance(code, str) for code in record.country_codes
    ):
        raise SourceEvidencePolicyError("The situation country scope is invalid.")
    if record.country_codes and query.country.alpha3_code not in record.country_codes:
        raise SourceEvidencePolicyError(
            "The situation country is outside the selected scope."
        )
    if record.reported_event_time is not None and not _aware(
        record.reported_event_time
    ):
        raise SourceEvidencePolicyError("The situation event time is invalid.")
    for fact in record.facts:
        if (
            not isinstance(fact, ReportedFact)
            or not isinstance(fact.category, str)
            or not fact.category.strip()
            or not isinstance(fact.label, str)
            or not fact.label.strip()
            or not isinstance(fact.value, str)
            or not fact.value.strip()
            or not isinstance(fact.status, FactStatus)
        ):
            raise SourceEvidencePolicyError("A reported fact is invalid.")
        _validate_source(fact.source, source_id=source_id, allowed_hosts=allowed_hosts)
        if fact.observed_at is not None and not _aware(fact.observed_at):
            raise SourceEvidencePolicyError("A reported fact time is invalid.")
    return record


def validate_worldwide_situation_evidence(
    record: object,
    query: WorldwideDisasterQuery,
    *,
    source_id: str,
    allowed_hosts: frozenset[str],
) -> SituationReport:
    """Validate situation evidence without inventing a country scope."""
    if not isinstance(record, SituationReport):
        raise SourceEvidencePolicyError(
            "The worldwide situation provider returned a wrong record type."
        )
    _validate_source(record.source, source_id=source_id, allowed_hosts=allowed_hosts)
    if not isinstance(record.narrative, str):
        raise SourceEvidencePolicyError("The worldwide situation narrative is invalid.")
    _validate_measurements(record.measurements, record.source)
    if record.disaster is not None and record.disaster != query.disaster:
        raise SourceEvidencePolicyError(
            "The worldwide situation disaster is outside the selected scope."
        )
    return record


def _validate_source(
    source: object, *, source_id: str, allowed_hosts: frozenset[str]
) -> None:
    if not isinstance(source, SourceReference):
        raise SourceEvidencePolicyError(
            "The record has no normalized source reference."
        )
    if not source_id or not allowed_hosts:
        raise SourceEvidencePolicyError("The provider has no approved source policy.")
    if not isinstance(source.source_id, str) or source.source_id != source_id:
        raise SourceEvidencePolicyError(
            "The record source ID is not registry-approved."
        )
    if (
        not isinstance(source.publisher, str)
        or not source.publisher.strip()
        or not isinstance(source.title, str)
        or not source.title.strip()
        or not isinstance(source.canonical_url, str)
        or not isinstance(source.authority, SourceAuthority)
    ):
        raise SourceEvidencePolicyError("The record source metadata is invalid.")
    try:
        target = urlsplit(source.canonical_url)
        port = target.port
    except ValueError as error:
        raise SourceEvidencePolicyError("The record source URL is invalid.") from error
    hostname = (target.hostname or "").lower().rstrip(".")
    approved = {item.lower().rstrip(".") for item in allowed_hosts}
    if (
        target.scheme.lower() != "https"
        or hostname not in approved
        or target.username is not None
        or target.password is not None
        or port not in {None, 443}
    ):
        raise SourceEvidencePolicyError(
            "The record source URL is not registry-approved."
        )
    for value in (source.published_at, source.updated_at, source.retrieved_at):
        if value is not None and not _aware(value):
            raise SourceEvidencePolicyError("A source timestamp is invalid.")


def _aware(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def _validate_geometry(
    geometry: object,
    source: SourceReference,
    *,
    approved_sources: frozenset[SourceReference] | None = None,
) -> None:
    if geometry is None:
        return
    if not isinstance(geometry, EventGeometry):
        raise SourceEvidencePolicyError("The event geometry is invalid.")
    if approved_sources is None and geometry.source != source:
        raise SourceEvidencePolicyError("The event geometry provenance is invalid.")
    if approved_sources is not None and geometry.source not in approved_sources:
        raise SourceEvidencePolicyError("The event geometry provenance is invalid.")
    if not isinstance(geometry.kind, EventGeometryKind):
        raise SourceEvidencePolicyError("The event geometry kind is invalid.")
    coordinate_count = len(geometry.coordinates)
    if geometry.kind is EventGeometryKind.POINT and coordinate_count != 1:
        raise SourceEvidencePolicyError("The point event geometry is invalid.")
    if geometry.kind is EventGeometryKind.AREA and coordinate_count < 3:
        raise SourceEvidencePolicyError("The area event geometry is invalid.")
    if geometry.kind is EventGeometryKind.TRACK and coordinate_count < 2:
        raise SourceEvidencePolicyError("The track event geometry is invalid.")
    if geometry.kind is EventGeometryKind.DESCRIPTIVE and (
        coordinate_count
        or not isinstance(geometry.description, str)
        or not geometry.description.strip()
    ):
        raise SourceEvidencePolicyError("The descriptive event geometry is invalid.")
    for coordinate in geometry.coordinates:
        if (
            not _finite_number(coordinate.latitude)
            or not _finite_number(coordinate.longitude)
            or not -90 <= coordinate.latitude <= 90
            or not -180 <= coordinate.longitude <= 180
        ):
            raise SourceEvidencePolicyError("The event geometry coordinate is invalid.")


def validate_physical_event_evidence(
    record: object,
    physical_event: PhysicalEventIdentity,
    query: DisasterQuery,
) -> DisasterEvent:
    """Validate an aggregate without erasing observation-level provenance."""
    if not isinstance(record, DisasterEvent):
        raise SourceEvidencePolicyError("The merged event has an invalid type.")
    if record.disaster != query.disaster or record.country.alpha3_code != (
        query.country.alpha3_code
    ):
        raise SourceEvidencePolicyError("The merged event is outside query scope.")
    if (
        not record.event_id.strip()
        or not record.location.strip()
        or not _aware(record.event_time)
    ):
        raise SourceEvidencePolicyError("The merged event identity or time is invalid.")
    observation_sources = {item.source for item in physical_event.observations}
    if record.source not in observation_sources:
        raise SourceEvidencePolicyError(
            "The merged event source is not one of its observations."
        )
    _validate_geometry(
        record.geometry,
        record.source,
        approved_sources=frozenset(observation_sources),
    )
    if record.geometry is not None and not any(
        item.geometry == record.geometry for item in physical_event.observations
    ):
        raise SourceEvidencePolicyError(
            "The merged event geometry is not an observed source geometry."
        )
    _validate_measurements(record.measurements, frozenset(observation_sources))
    for measurement in record.measurements:
        measurement_source = getattr(measurement, "source", None)
        if measurement_source not in observation_sources or not any(
            measurement in item.measurements for item in physical_event.observations
        ):
            raise SourceEvidencePolicyError(
                "The merged event measurement provenance is invalid."
            )
    return record


def _validate_measurements(
    measurements: object, source: SourceReference | frozenset[SourceReference]
) -> None:
    if not isinstance(measurements, tuple) or any(
        not isinstance(measurement, EventMeasurement) for measurement in measurements
    ):
        raise SourceEvidencePolicyError("The event measurements are invalid.")
    for measurement in measurements:
        if not isinstance(getattr(measurement, "kind", None), MeasurementKind):
            raise SourceEvidencePolicyError("The event measurement kind is invalid.")
        measurement_source = getattr(measurement, "source", None)
        if (
            measurement_source != source
            if isinstance(source, SourceReference)
            else measurement_source not in source
        ):
            raise SourceEvidencePolicyError(
                "The event measurement provenance is invalid."
            )
        if isinstance(measurement.value, float) and not _finite_number(
            measurement.value
        ):
            raise SourceEvidencePolicyError("An event measurement value is invalid.")
