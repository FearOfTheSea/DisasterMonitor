"""Admit event-linked GDACS volcanic ash advisory text as preliminary evidence."""

import re
from datetime import datetime
from urllib.parse import urlencode

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.ports.provider_text import sanitize_provider_text
from disaster_monitor.application.ports.temporal_normalization import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    FactStatus,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)


def eruption_ash_report(
    properties: dict[str, object],
    event: DisasterEvent,
    query: DisasterQuery,
    *,
    event_identifier: str,
    source_id: str,
    snapshot_id: str | None,
    now: datetime,
) -> SituationReport | None:
    """Retain only explicit ash text from the validated GDACS event detail."""
    if event.disaster is not Disaster.VOLCANIC_ERUPTION:
        return None
    additional = properties.get("additionalinfos")
    if not isinstance(additional, dict):
        return None
    raw_detail = additional.get("eruptiondetails")
    if not isinstance(raw_detail, str) or len(raw_detail) > 500:
        return None
    detail = sanitize_provider_text(raw_detail, limit=240)
    if not detail or not re.search(r"\bash\b", detail, re.IGNORECASE):
        return None
    source_name = properties.get("source")
    publisher = "GDACS"
    if isinstance(source_name, str):
        admitted_source = sanitize_provider_text(source_name, limit=60)
        if admitted_source:
            publisher += f"; source: {admitted_source}"
    source = SourceReference(
        source_id=source_id,
        publisher=publisher,
        title="Volcanic ash advisory summary",
        canonical_url=(
            "https://www.gdacs.org/gts.aspx?"
            + urlencode({"eventtype": "VO", "eventid": event_identifier})
        ),
        published_at=None,
        updated_at=normalize_timestamp(properties.get("datemodified")),
        retrieved_at=now,
        authority=SourceAuthority.SECONDARY,
        snapshot_id=snapshot_id,
    )
    fact = ReportedFact(
        category="ash_observation",
        label="Volcanic ash advisory",
        value=detail,
        status=FactStatus.PRELIMINARY,
        source=source,
        event_id=event.event_id,
        claim_id=f"gdacs:vo:{event_identifier}:eruptiondetails",
    )
    return SituationReport(
        source=source,
        narrative=(
            "GDACS relays an event-linked volcanic ash advisory. It does not "
            "establish ash fall on the ground or human impact."
        ),
        facts=(fact,),
        event_id=event.event_id,
        reported_event_time=event.event_time,
        country_codes=(query.country.alpha3_code,),
        disaster=query.disaster,
    )
