"""Keep same-article response context with its uniquely dated place anchor.

This is narrative continuity, not independent corroboration or cross-report event
matching. Other places, competing onset anchors and independent occurrence accounts
remain separate.
"""

import re
from dataclasses import replace

from disaster_monitor.domain.event_mentions import EventMention
from disaster_monitor.domain.mention_occurrence import (
    has_distinct_occurrence,
    is_response_context,
)

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


def consolidate_response_context(mentions: list[EventMention]) -> list[EventMention]:
    attachments: dict[int, list[int]] = {}
    for index, mention in enumerate(mentions):
        if (
            mention.time is not None
            or mention.role not in ("reported", "uncertain")
            or not is_response_context(mention.text)
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
                    "Undated same-place response passages retained with the only "
                    "dated occurrence in this article. They do not establish "
                    "another onset or independent confirmation.",
                ),
            )
        result.append(mention)
    return result
