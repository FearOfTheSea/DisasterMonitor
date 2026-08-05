"""Normalize provider records into a bounded, source-attributed evidence packet."""

import re
from datetime import UTC, datetime, timedelta
from html import unescape

from disaster_monitor.application.disaster import (
    DisasterEvent,
    DisasterQuery,
    EvidencePacket,
    FactStatus,
    ReportedFact,
    SituationReport,
    SourceReference,
)

MAX_NARRATIVE_LENGTH = 1_200
_TAG = re.compile(r"<[^>]+>")
_INSTRUCTION_FRAGMENT = re.compile(
    r"\b(?:ignore|disregard|override|system message|developer message|"
    r"tool call|prompt injection)(?:\s+\w+){0,4}[.!?:;]?",
    re.IGNORECASE,
)


def sanitize_provider_text(text: str, *, limit: int = MAX_NARRATIVE_LENGTH) -> str:
    """Remove markup, control characters, and instruction-like provider text."""
    cleaned = _TAG.sub(" ", unescape(text))
    lines = []
    for line in cleaned.splitlines():
        safe_line = _INSTRUCTION_FRAGMENT.sub(" ", line)
        safe_line = re.sub(r"\s+", " ", safe_line).strip()
        if safe_line:
            lines.append(safe_line)
    cleaned = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return cleaned[:limit]


def normalize_timestamp(value: object) -> datetime | None:
    """Normalize ISO-8601, Unix-millisecond, and compact JMA timestamps."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 100_000_000_000:
            number /= 1_000
        return datetime.fromtimestamp(number, tz=UTC)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if re.fullmatch(r"\d{14}", text):
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _source_key(source: SourceReference) -> str:
    return source.canonical_url.rstrip("/").lower()


def _source_priority(source: SourceReference) -> int:
    publisher = source.publisher.lower()
    if "japan meteorological agency" in publisher or publisher == "jma":
        return 4
    if "united states geological survey" in publisher or publisher == "usgs":
        return 4
    if "reliefweb" in publisher:
        return 2
    return 1


def _fact_key(fact: ReportedFact) -> str:
    return fact.claim_id or fact.category


def _deduplicate_reports(
    reports: tuple[SituationReport, ...],
) -> tuple[SituationReport, ...]:
    unique: dict[str, SituationReport] = {}
    for report in reports:
        narrative_key = re.sub(r"\W+", " ", report.narrative.lower()).strip()[:240]
        key = narrative_key if len(narrative_key) >= 40 else _source_key(report.source)
        if key not in unique:
            unique[key] = report
            continue
        current = unique[key]
        if report.source.effective_at > current.source.effective_at:
            unique[key] = report
    return tuple(unique.values())


def build_evidence_packet(
    query: DisasterQuery,
    event: DisasterEvent,
    reports: tuple[SituationReport, ...],
    *,
    warnings: tuple[str, ...],
    retrieved_at: datetime,
) -> EvidencePacket:
    """Reconcile duplicate, newer, missing, and conflicting provider facts."""
    reports = _deduplicate_reports(reports)
    candidates: dict[str, list[ReportedFact]] = {}
    for report in reports:
        for fact in report.facts:
            safe_value = sanitize_provider_text(fact.value, limit=240)
            if not safe_value:
                continue
            normalized = ReportedFact(
                category=fact.category,
                label=sanitize_provider_text(fact.label, limit=120),
                value=safe_value,
                status=fact.status,
                source=fact.source,
                event_id=fact.event_id or report.event_id or event.event_id,
                observed_at=fact.observed_at,
                claim_id=fact.claim_id,
            )
            candidates.setdefault(_fact_key(normalized), []).append(normalized)

    selected: list[ReportedFact] = []
    conflicts: list[str] = []
    for claim_key, facts in candidates.items():
        distinct_values = {fact.value.lower() for fact in facts}
        ordered = sorted(
            facts,
            key=lambda fact: (
                _source_priority(fact.source),
                fact.source.effective_at,
                fact.status == FactStatus.CONFIRMED,
            ),
            reverse=True,
        )
        selected.append(ordered[0])
        if len(distinct_values) > 1:
            summary = "; ".join(
                f"{fact.source.publisher}: {fact.value}" for fact in ordered[:4]
            )
            conflicts.append(f"{ordered[0].label or claim_key}: {summary}.")

    sources: list[SourceReference] = [event.source]
    for report in reports:
        if _source_key(report.source) not in {_source_key(item) for item in sources}:
            sources.append(report.source)
    stale = any(
        retrieved_at - source.effective_at > timedelta(hours=24) for source in sources
    )
    stale_warning = (
        ("Some source updates are stale (more than 24 hours old).",) if stale else ()
    )
    narratives = tuple(
        narrative
        for narrative in (
            sanitize_provider_text(report.narrative) for report in reports
        )
        if narrative
    )
    return EvidencePacket(
        query=query,
        event=event,
        facts=tuple(sorted(selected, key=lambda fact: (fact.category, fact.label))),
        narratives=narratives[:6],
        sources=tuple(sources[:10]),
        conflicts=tuple(conflicts[:8]),
        warnings=tuple(dict.fromkeys((*warnings, *stale_warning))),
        retrieved_at=retrieved_at,
        stale=stale,
    )
