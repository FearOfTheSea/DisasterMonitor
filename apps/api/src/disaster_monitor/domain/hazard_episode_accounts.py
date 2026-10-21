"""Retain explicitly dated joint report accounts without allocating their impacts.

This bounded rule requires one combined occurrence and an explicit event-date field.
It does not reconcile different reports or turn joint figures into hazard totals.
"""

import hashlib
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.domain.discovery_claim_scope import has_competing_cause
from disaster_monitor.domain.event_mentions import (
    EventMention,
    HazardEpisodeAccount,
    MentionTime,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.mention_occurrence import (
    has_distinct_occurrence,
    occurrence_role,
)
from disaster_monitor.domain.reported_impacts import extract_reported_impacts


def _event_date(text: str) -> MentionTime | None:
    fields = re.findall(
        r"(?im)^[ \t]*Date of event[ \t]*:?[ \t]*(?:\n[ \t]*)+([^\n]+)",
        re.sub(r"[*#]", "", text),
    )
    if len(fields) != 1:
        return None
    wording = fields[0].strip()
    parts = re.fullmatch(r"(\d{2}|\d{4})-(\d{2})-(\d{2}|\d{4})", wording)
    if not parts:
        return None
    first, month, last = (int(value) for value in parts.groups())
    if first > 999 and last <= 31:
        year, day = first, last
    elif first > 12 and last > 999:
        day, year = first, last
    else:
        return None  # Ambiguous numeric local formats do not establish an onset.
    try:
        start = datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None
    return MentionTime(wording, start, start + timedelta(days=1), "day")


def attach_hazard_episode_accounts(
    mentions: list[EventMention], text: str, source: SourceReference
) -> list[EventMention]:
    hazards = disasters_in_text(source.title)
    time = _event_date(text)
    if (
        len(hazards) < 2
        or time is None
        or (
            time.start is not None
            and source.published_at is not None
            and time.start > source.published_at + timedelta(days=1)
        )
        or has_competing_cause(text)
        or set(disasters_in_text(text)) - set(hazards)
        or any(
            m.role == "historical"
            or has_distinct_occurrence(m.excerpt)
            or (
                m.role in ("reported", "ongoing")
                and m.time
                and m.time.start
                and m.time.start != time.start
            )
            for m in mentions
        )
    ):
        return mentions
    anchors = {
        m.excerpt: m
        for m in mentions
        if m.role in ("reported", "ongoing")
        and m.place
        and m.place.precision == "named_place"
        and set(disasters_in_text(m.excerpt)) == set(hazards)
    }
    if len(anchors) != 1:
        return mentions
    excerpt, anchor = next(iter(anchors.items()))
    assert anchor.place is not None
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text[:20_000])
        if occurrence_role(paragraph) in ("reported", "ongoing")
        and (
            not disasters_in_text(paragraph)
            or set(disasters_in_text(paragraph)) == set(hazards)
        )
    ]
    supporting = "\n\n".join(paragraphs)
    claims = extract_reported_impacts(supporting, source)
    if not claims:
        return mentions
    account = HazardEpisodeAccount(
        "episode:"
        + hashlib.sha256(
            f"{source.canonical_url}|{time.wording}|{excerpt}|{supporting}".encode()
        ).hexdigest()[:24],
        hazards,
        anchor.place,
        time,
        supporting,
        claims,
    )
    return [
        replace(
            m,
            time=time,
            episode_account=account,
            claims=(),
            notices=(
                *m.notices,
                "Explicit Date of event field supplies this combined episode's "
                "reported date. Joint impacts are not allocated to individual "
                "hazards or localities. Original passages retain their scope.",
            ),
        )
        if m.excerpt == excerpt
        else m
        for m in mentions
    ]
