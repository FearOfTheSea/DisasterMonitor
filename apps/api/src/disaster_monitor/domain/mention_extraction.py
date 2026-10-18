"""Bounded English mention extraction; every normalized field retains its wording.

No model, publisher catalog, network, or benchmark identity is involved. Unsupported
language and implicit references remain unresolved rather than acquiring invented facts.
"""

import hashlib
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery_claim_scope import scoped_disaster_text
from disaster_monitor.domain.event_mentions import (
    EventMention,
    MentionPlace,
    MentionTime,
)
from disaster_monitor.domain.events import EventGeometry
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.mention_occurrence import (
    date_is_occurrence,
    occurrence_role,
)
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

_MONTHS = (
    "January February March April May June July August September "
    "October November December"
).split()
_MONTH = "|".join(_MONTHS)
_DATE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:(?:[-–]|\s+to\s+)(?P<last>\d{{1,2}}))?\s+(?P<month>{_MONTH})(?:\s+(?P<year>20\d{{2}}|19\d{{2}}))?\b",
    re.I,
)
_US_DATE = re.compile(
    rf"\b(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}})(?:,?\s+(?P<year>20\d{{2}}|19\d{{2}}))?\b",
    re.I,
)
_WORD = r"[A-ZÀ-Ý][\wÀ-ž’'-]*(?:\s+(?:[A-ZÀ-Ý][\wÀ-ž’'-]*|of|the|and|&)){0,4}"
_PLACE = re.compile(
    rf"\b(?i:in|near|struck|hit|centred in|centered in|affected)\s+(?P<place>{_WORD})"
)
_ADMINISTRATIVE_PLACE = re.compile(
    r"\b(?P<place>[A-ZÀ-Ý][\wÀ-ž’'-]*(?:(?:,\s*|\s+and\s+|\s+)[A-ZÀ-Ý][\wÀ-ž’'-]*)*"
    r"\s+(?:districts?|provinces?|municipalit(?:y|ies)))\b",
)
_STORM = re.compile(r"\b(?:Hurricane|Typhoon|Cyclone|Tropical Storm)\s+([A-Z][a-z]+)\b")


def _historical(text: str, source: SourceReference) -> bool:
    return bool(
        re.search(
            r"\b(?:historical|anniversary|years? ago|last year|"
            r"previous event|similar to)\b",
            text,
            re.I,
        )
    ) or bool(
        source.published_at
        and any(
            int(y) < source.published_at.year
            for y in re.findall(r"\bin ((?:19|20)\d{2})\b", text, re.I)
        )
    )


def _time(text: str, source: SourceReference) -> MentionTime | None:
    matches = list(_DATE.finditer(text)) + list(_US_DATE.finditer(text))
    matches = [m for m in matches if date_is_occurrence(text, m.start(), m.end())]
    if not matches:
        approximate = re.search(
            rf"\b(?:early|mid|late)\s+(?:{_MONTH})(?:\s+20\d{{2}})?\b", text, re.I
        )
        if approximate and date_is_occurrence(
            text, approximate.start(), approximate.end()
        ):
            return MentionTime(approximate[0])
        return None
    if len({m.group().casefold() for m in matches}) > 1:
        # A dateline, activity date, and occurrence date need separate scope.
        # Preserve the passage instead of choosing the first clock as onset.
        return None
    match = matches[0]
    year = match["year"]
    publication = source.published_at
    if year is None and publication is None:
        return MentionTime(match.group())
    month = next(
        i + 1
        for i, name in enumerate(_MONTHS)
        if name.casefold() == match["month"].casefold()
    )
    try:
        start = datetime(
            int(year) if year else publication.year if publication else 0,
            month,
            int(match["day"]),
            tzinfo=UTC,
        )
        if year is None and publication and start > publication + timedelta(days=1):
            start = start.replace(year=start.year - 1)
        last = match.groupdict().get("last")
        end = (
            start.replace(day=int(last)) + timedelta(days=1)
            if last
            else start + timedelta(days=1)
        )
        return MentionTime(
            match.group(), start, end, "range" if last else "day", year is None
        )
    except ValueError:
        return MentionTime(match.group())


def _place(text: str) -> MentionPlace | None:
    administrative = _ADMINISTRATIVE_PLACE.search(text)
    if administrative:
        return MentionPlace(
            administrative["place"], "named_place", "administrative_area"
        )
    matches = list(_PLACE.finditer(text))
    if not matches:
        return None
    # An explicit named location is descriptive until a geographic source resolves it.
    value = matches[0]["place"].strip(" ,.;:&")
    if value.casefold() in {month.casefold() for month in _MONTHS}:
        return None
    if value in {"The", "National", "Government", "October", "November"}:
        return None
    return MentionPlace(value, "named_place")


def extract_mentions(
    text: str,
    source: SourceReference,
    *,
    location: str | None = None,
    event_time: datetime | None = None,
    geometry: EventGeometry | None = None,
    country_names: frozenset[str] = frozenset(),
) -> tuple[EventMention, ...]:
    """Extract anchors and attach contiguous, compatible source context."""
    title_hazards = disasters_in_text(source.title)
    title_place = _place(source.title) if len(title_hazards) == 1 else None
    # Markdown headings from report bodies are event context, never discarded markup.
    normalized = re.sub(
        r"\*\*([^*]+)\*\*",
        lambda m: f"\n{m[1]}\n" if m[1].isupper() and len(m[1]) < 100 else m[1],
        text[:20_000],
    )
    # Titles such as Dr. must not become standalone heading-inherited mentions.
    sentences = [
        s.strip(" •-\n")
        for s in re.split(
            r"(?<!Dr\.)(?<!Mr\.)(?<!Mrs\.)(?<!Ms\.)(?<=[.!?])\s+|\n+|\s+[•]\s+|\s+-\s+",
            normalized,
        )
        if s.strip(" •-\n")
    ]
    mentions: list[EventMention] = []
    active: list[int] = []
    heading_hazards: tuple[Disaster, ...] = ()
    heading_place: MentionPlace | None = None
    heading_names: tuple[str, ...] = ()
    for sentence in sentences:
        unresolved_scope = False
        hazards = disasters_in_text(sentence)
        if sentence.startswith("#"):
            heading_text = sentence.lstrip("# ")
            if re.fullmatch(
                r"(?:in the news|related(?: stories| articles| content)?|"
                r"what we.re reading|filed under|tags|media contacts|"
                r"additional resources|"
                r"related topics|about .*)\s*:?",
                heading_text,
                re.I,
            ):
                break
            heading_hazards = hazards
            heading_place = _place(heading_text)
            heading_names = tuple(dict.fromkeys(_STORM.findall(heading_text)))
            active = []
            continue
        heading = (
            re.fullmatch(r"([^:–]+)\s*[:–]\s*([^:–]+)", sentence)
            if len(sentence) < 100
            else None
        )
        if heading and hazards and not re.search(r"[.!?]|\d", sentence):
            heading_hazards = hazards
            location_part = heading[2] if disasters_in_text(heading[1]) else heading[1]
            heading_place = MentionPlace(
                location_part.strip().title(), "country_context", "administrative_area"
            )
            active = []
            continue
        if not hazards:
            new_place = _place(sentence)
            if (
                active
                and new_place
                and all(
                    mentions[index].place
                    and mentions[index].place != new_place
                    and not (
                        mentions[index].name
                        and re.search(
                            rf"\b{re.escape(mentions[index].name or '')}\b",
                            sentence,
                            re.I,
                        )
                    )
                    for index in active
                )
            ):
                hazards = tuple(
                    dict.fromkeys(mentions[index].disaster for index in active)
                )
                unresolved_scope = True
            elif not active and heading_hazards:
                hazards = heading_hazards
            else:
                if active:
                    for index in active:
                        mention = mentions[index]
                        if _historical(sentence, source) or _STORM.search(sentence):
                            active = []
                            break
                        mentions[index] = replace(
                            mention, text=f"{mention.text} {sentence}"
                        )
                continue
        place = _place(sentence)
        time = _time(sentence, source)
        names = tuple(dict.fromkeys(_STORM.findall(sentence))) or (
            heading_names if Disaster.TROPICAL_CYCLONE in hazards else ()
        )
        role = (
            "uncertain"
            if unresolved_scope
            else occurrence_role(sentence, historical=_historical(sentence, source))
        )
        # One clause describing several hazards retains unallocated accounts as text.
        mixed = len(hazards) > 1 or len(names) > 1
        preceding_active = active
        active = []
        for hazard in hazards:
            if hazard is Disaster.DROUGHT and not re.search(
                r"\b(?:since|began|started|onset)\b", sentence, re.I
            ):
                time = None
            if (
                place is None
                and time is None
                and not names
                and preceding_active
                and mentions[preceding_active[-1]].disaster == hazard
                and not mixed
            ):
                place = mentions[preceding_active[-1]].place
            place = place or heading_place
            if place is None and title_hazards == (hazard,):
                place = title_place
            if place and (
                place.wording.casefold() in country_names
                or (location and place.wording.casefold() == location.casefold())
            ):
                place = replace(
                    place, precision="country_context", role="administrative_area"
                )
            # Repeated named-place evidence in one article can join across another
            # event, but unknown geography/time cannot bridge independent events.
            matching = [
                i
                for i, m in enumerate(mentions)
                if m.disaster == hazard
                and m.role == role
                and not mixed
                and place is not None
                and m.place == place
                and m.time == time
                and (not names or m.name == names[0])
            ]
            previous_index = matching[0] if len(matching) == 1 else len(mentions) - 1
            previous = mentions[previous_index] if mentions else None
            if (
                previous
                and previous.disaster == hazard
                and not mixed
                and (place is None or previous.place == place)
                and (time is None or previous.time == time)
                and (
                    role == previous.role
                    or (
                        role == "uncertain"
                        and time is None
                        and (place is None or place == previous.place)
                    )
                )
                and (not names or previous.name == names[0])
            ):
                index = previous_index
                mentions[index] = replace(previous, text=f"{previous.text} {sentence}")
                active.append(index)
                continue
            original_place = place
            if place is None and len(title_hazards) == 1 and location:
                place = MentionPlace(location, "country_context", "administrative_area")
            if time is None and event_time is not None and len(title_hazards) == 1:
                time = MentionTime(
                    event_time.isoformat(), event_time, event_time, "exact"
                )
            material = f"{source.canonical_url}|{hazard}|{len(mentions)}"
            mention = EventMention(
                mention_id="mention:"
                + hashlib.sha256(material.encode()).hexdigest()[:24],
                source=source,
                disaster=hazard,
                text=sentence,
                excerpt=sentence,
                place=place,
                time=time,
                name=names[0]
                if len(names) == 1 and hazard is Disaster.TROPICAL_CYCLONE
                else None,
                role=role,
                country_context=heading_place.wording
                if heading_place and heading_place.wording.casefold() in country_names
                else location
                if len(title_hazards) == 1
                else None,
                geometry=geometry if len(title_hazards) == 1 and not mixed else None,
                notices=(
                    "Combined hazard or named-event account: "
                    "impacts cannot be uniquely allocated.",
                )
                if mixed
                else (
                    "Geographic scope changed without an explicit event link; "
                    "claims remain unallocated.",
                )
                if unresolved_scope
                else (),
                distinguishing_evidence=(
                    m.group()
                    if (
                        m := re.search(
                            r"(?:magnitude\s+\d\.\d|\d\.\d[- ]magnitude|aftershock)",
                            sentence,
                            re.I,
                        )
                    )
                    else None
                ),
            )
            mentions.append(mention)
            active.append(len(mentions) - 1)
            place = original_place
    if not mentions and len(title_hazards) == 1:
        hazard = title_hazards[0]
        mentions.append(
            EventMention(
                "mention:"
                + hashlib.sha256(
                    f"{source.canonical_url}|{hazard}|0".encode()
                ).hexdigest()[:24],
                source,
                hazard,
                text[:20_000],
                source.title,
                title_place
                or (
                    MentionPlace(location, "country_context", "administrative_area")
                    if location
                    else None
                ),
                MentionTime(event_time.isoformat(), event_time, event_time, "exact")
                if event_time
                else None,
                geometry=geometry,
                role=occurrence_role(text or source.title),
                notices=(
                    "Headline-only hazard context; event fields may remain unresolved.",
                ),
            )
        )
    result = []
    for mention in mentions[:80]:
        role = mention.role
        scoped = scoped_disaster_text(
            mention.text, mention.disaster.value.replace("_", " "), mention.disaster
        )
        claims = (
            ()
            if role in ("forecast", "uncertain")
            or (mention.notices and mention.notices[0].startswith("Combined"))
            else extract_reported_impacts(
                scoped,
                source,
                location=mention.place.wording if mention.place else None,
            )
        )
        result.append(
            replace(
                mention,
                claims=claims,
                notices=(
                    *mention.notices,
                    *(
                        ("Mention limit reached; source retained.",)
                        if len(mentions) > 80
                        else ()
                    ),
                ),
            )
        )
    return tuple(result)
