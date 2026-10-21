"""Keep same-article local accounts with their uniquely dated place anchor.

This is narrative continuity, not independent corroboration or cross-report event
matching. Other places, competing onset anchors and independent occurrence accounts
remain separate.
"""

import re
from dataclasses import replace

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.event_mentions import EventMention, MentionPlace
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.mention_occurrence import (
    has_distinct_occurrence,
    is_response_context,
    is_victim_firefighting_activity,
    occurrence_role,
    reported_magnitude,
)
from disaster_monitor.domain.reported_impacts import extract_reported_impacts
from disaster_monitor.domain.source_sentences import source_sentences

_PLACE_CONTEXT = frozenset(
    {
        "in",
        "the",
        "and",
        "district",
        "districts",
        "province",
        "provinces",
        "municipality",
        "municipalities",
    }
)


def _place_names(mention: EventMention) -> set[str]:
    if not mention.place or mention.place.precision != "named_place":
        return set()
    return {
        word.casefold()
        for word in re.findall(r"[\wÀ-ž’'-]+", mention.place.wording)
        if word.casefold() not in _PLACE_CONTEXT and not word.endswith(("'s", "’s"))
    }


def local_context_target(
    mentions: list[EventMention], active: list[int], place: MentionPlace | None
) -> int | None:
    """An explicit place may return to one previously reported local account.

    A changed place with no earlier occurrence remains unresolved. Multiple local
    occurrences and combined hazards prevent choosing a target by name alone.
    """
    hazards = {mentions[i].disaster for i in active}
    if place is None or len(hazards) != 1:
        return None
    candidates = [
        i
        for i, mention in enumerate(mentions)
        if mention.disaster in hazards
        and mention.place is not None
        and mention.place.wording.casefold() == place.wording.casefold()
        and mention.role in ("reported", "ongoing")
    ]
    if len(candidates) != 1:
        return None
    index = candidates[0]
    if any(n.startswith("Combined") for n in mentions[index].notices):
        return None
    return index


def explicit_wildfire_reference_target(
    mentions: list[EventMention], preceding: list[str], sentence: str
) -> int | None:
    """Resolve a nearby explicit reference to one typed physical wildfire.

    The reference must itself supply an occurrence action. It cannot bridge a
    heading, another hazard or another fire. The caller checks its date and place.
    """
    victim_activity = is_victim_firefighting_activity(sentence)
    if not victim_activity and not re.match(
        r"^The\s+(?:fire|blaze)\s+(?:ignited|started|began|broke out)\b",
        sentence,
        re.I,
    ):
        return None
    if any(s.startswith("#") for s in preceding):
        return None
    context = " ".join(preceding)
    if disasters_in_text(context) != (Disaster.WILDFIRE,):
        return None
    candidates = [
        i
        for i, m in enumerate(mentions)
        if m.disaster is Disaster.WILDFIRE
        and m.role in ("reported", "ongoing")
        and m.excerpt in preceding
        and not m.occurrence_anchor_id
        and not any(n.startswith("Combined") for n in m.notices)
    ]
    if len(candidates) != 1:
        return None
    index = candidates[0]
    if victim_activity and not any(
        c.fact.category in ("fatalities", "injuries")
        for c in extract_reported_impacts(mentions[index].text, mentions[index].source)
    ):
        return None
    tail = " ".join(preceding[preceding.index(mentions[index].excerpt) + 1 :])
    if has_distinct_occurrence(context) or re.search(
        r"\b(?:a|an|another|separate|different|new)\s+"
        r"(?:[\w-]+\s+){0,2}(?:fire|blaze)\b",
        tail,
        re.I,
    ):
        return None
    return index


def consolidate_local_context(mentions: list[EventMention]) -> list[EventMention]:
    attachments: dict[int, list[int]] = {}
    for index, mention in enumerate(mentions):
        if (
            mention.time is not None
            or mention.role not in ("reported", "uncertain")
            or (mention.role == "uncertain" and not is_response_context(mention.text))
            or mention.name
            or mention.distinguishing_evidence
            or any(notice.startswith("Combined") for notice in mention.notices)
            or has_distinct_occurrence(mention.excerpt)
            or not (names := _place_names(mention))
        ):
            continue
        anchors = [
            i
            for i, candidate in enumerate(mentions)
            if candidate.disaster == mention.disaster
            and candidate.role in ("reported", "ongoing")
            and candidate.time
            and candidate.time.start
        ]
        if len(anchors) != 1:
            continue
        anchor = anchors[0]
        if names <= _place_names(mentions[anchor]):
            attachments.setdefault(anchor, []).append(index)
    removed = {i for indexes in attachments.values() for i in indexes}
    result = []
    for index, mention in enumerate(mentions):
        if index in removed:
            continue
        if index in attachments:
            indexes = sorted([index, *attachments[index]])
            mention = replace(
                mention,
                text=" ".join(mentions[i].text for i in indexes),
                notices=(
                    *mention.notices,
                    "Undated same-place passages retained with the only "
                    "dated occurrence in this article. They do not establish "
                    "another onset or independent confirmation.",
                ),
            )
        result.append(mention)
    return result


def attach_listed_place_periods(mentions: list[EventMention]) -> list[EventMention]:
    """Share a unique occurrence clock only with explicitly listed affected places.

    Keep each place's passage and impacts separate. A region's casualty account
    must never move to a listed locality. Unrelated place references, forecasts,
    competing dates and separately reported occurrences cannot establish a link.
    """
    result = []
    for mention in mentions:
        if (
            mention.time is not None
            or mention.role not in ("reported", "ongoing")
            or not mention.place
            or mention.place.precision != "named_place"
            or has_distinct_occurrence(mention.excerpt)
            or mention.distinguishing_evidence
            or any(n.startswith("Combined") for n in mention.notices)
        ):
            result.append(mention)
            continue
        candidates = [m for m in mentions if m.disaster == mention.disaster]
        anchors = [
            m
            for m in candidates
            if m.time and m.time.start and m.role in ("reported", "ongoing")
        ]
        if len(anchors) != 1 or any(
            has_distinct_occurrence(m.excerpt) for m in candidates
        ):
            result.append(mention)
            continue
        anchor = anchors[0]
        listings = []
        for sentence in source_sentences(anchor.text):
            listing = re.fullmatch(
                r"(?:The\s+)?affected\s+(?:areas|districts|provinces|townships)\s+"
                r"(?:include|are)\s+(.+?)[.]?",
                sentence.strip(),
                re.I,
            )
            if not listing or occurrence_role(sentence) == "forecast":
                continue
            places = re.split(r",\s*|\s+and\s+", listing[1].rstrip("."), flags=re.I)
            if mention.place.wording.casefold() in {
                p.strip().casefold() for p in places
            }:
                listings.append(sentence)
        if listings and disasters_in_text(anchor.excerpt) == (mention.disaster,):
            mention = replace(
                mention,
                time=anchor.time,
                notices=(
                    *mention.notices,
                    "Event period linked through this article's only dated "
                    f"{mention.disaster.value} occurrence: {anchor.excerpt} "
                    + " ".join(listings)
                    + " Local impact accounts retain their own scope.",
                ),
            )
        result.append(mention)
    return result


def link_earthquake_country_accounts(
    mentions: list[EventMention],
) -> list[EventMention]:
    """Link a national account to a unique dated magnitude anchor in this article.

    This is an identity link, not movement of local or national impact scope. Other
    dated quakes, distinct local occurrences and undated aftershocks block the link.
    """
    occurred = [
        m
        for m in mentions
        if m.disaster is Disaster.EARTHQUAKE and m.role in ("reported", "ongoing")
    ]
    anchors = [
        m
        for m in occurred
        if m.time
        and m.time.start
        and reported_magnitude(m.distinguishing_evidence) is not None
    ]
    if len(anchors) != 1:
        return mentions
    anchor = anchors[0]

    def repeats_country_magnitude(mention: EventMention) -> bool:
        return bool(
            mention.place
            and mention.place.precision == "country_context"
            and mention.country_context
            == anchor.country_context
            == mention.place.wording
            and reported_magnitude(mention.distinguishing_evidence)
            == reported_magnitude(anchor.distinguishing_evidence)
        )

    if any(
        m is not anchor
        and (
            m.time is not None
            or (m.distinguishing_evidence and not repeats_country_magnitude(m))
            or has_distinct_occurrence(m.excerpt)
            or (m.place and m.place.precision == "named_place")
        )
        for m in occurred
    ):
        return mentions
    if disasters_in_text(anchor.source.title) != (Disaster.EARTHQUAKE,):
        return mentions
    return [
        replace(
            m,
            time=anchor.time,
            occurrence_anchor_id=anchor.mention_id,
            notices=(
                *m.notices,
                "This country account refers to this article's only dated "
                f"magnitude occurrence: {anchor.excerpt} Impact accounts retain "
                "their country scope and are not allocated to the epicentre.",
            ),
        )
        if m is not anchor
        and m in occurred
        and m.place
        and m.place.precision == "country_context"
        and m.country_context == anchor.country_context == m.place.wording
        else m
        for m in mentions
    ]
