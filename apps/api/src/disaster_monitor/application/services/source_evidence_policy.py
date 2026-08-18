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
    DisasterEvent,
    FactStatus,
    Hazard,
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
    if not isinstance(record.hazard, Hazard) or record.hazard != query.hazard:
        raise SourceEvidencePolicyError(
            "The event hazard is outside the selected scope."
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
    if record.latitude is not None and (
        not _finite_number(record.latitude) or not -90 <= record.latitude <= 90
    ):
        raise SourceEvidencePolicyError("The event latitude is invalid.")
    if record.longitude is not None and (
        not _finite_number(record.longitude) or not -180 <= record.longitude <= 180
    ):
        raise SourceEvidencePolicyError("The event longitude is invalid.")
    if record.magnitude is not None and not _finite_number(record.magnitude):
        raise SourceEvidencePolicyError("The event magnitude is invalid.")
    if record.depth_km is not None and (
        not _finite_number(record.depth_km) or record.depth_km < 0
    ):
        raise SourceEvidencePolicyError("The event depth is invalid.")
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
    if record.hazard != query.hazard:
        raise SourceEvidencePolicyError(
            "The worldwide event hazard is outside the selected scope."
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
    if record.latitude is None or (
        not _finite_number(record.latitude) or not -90 <= record.latitude <= 90
    ):
        raise SourceEvidencePolicyError("The worldwide event latitude is invalid.")
    if record.longitude is None or (
        not _finite_number(record.longitude) or not -180 <= record.longitude <= 180
    ):
        raise SourceEvidencePolicyError("The worldwide event longitude is invalid.")
    if record.magnitude is not None and not _finite_number(record.magnitude):
        raise SourceEvidencePolicyError("The worldwide event magnitude is invalid.")
    if record.depth_km is not None and (
        not _finite_number(record.depth_km) or record.depth_km < 0
    ):
        raise SourceEvidencePolicyError("The worldwide event depth is invalid.")
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
    if record.hazard is not None and (
        not isinstance(record.hazard, Hazard) or record.hazard != query.hazard
    ):
        raise SourceEvidencePolicyError(
            "The situation hazard is outside the selected scope."
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
    if record.hazard is not None and record.hazard != query.hazard:
        raise SourceEvidencePolicyError(
            "The worldwide situation hazard is outside the selected scope."
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
