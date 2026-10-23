"""Bounded literal mention extraction; normalized fields retain their source wording.

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
from disaster_monitor.domain.hazard_episode_accounts import (
    attach_hazard_episode_accounts,
)
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.mention_context import (
    attach_listed_place_periods,
    consolidate_local_context,
    explicit_wildfire_reference_target,
    link_earthquake_country_accounts,
    local_context_target,
)
from disaster_monitor.domain.mention_occurrence import (
    date_is_occurrence,
    has_distinct_occurrence,
    has_individual_aftershock,
    is_felt_extent,
    is_victim_firefighting_activity,
    local_impact_context,
    occurrence_detail,
    occurrence_role,
    occurrence_years,
    same_occurrence_detail,
    victim_activity_date_requires_reference,
)
from disaster_monitor.domain.reported_impacts import extract_reported_impacts
from disaster_monitor.domain.source_sentences import source_sentences

_MONTHS = (
    "January February March April May June July August September "
    "October November December"
).split()
_MONTH = (
    "|".join(
        name + ("|" + name[:3] + r"\.?" if len(name) > 3 else "") for name in _MONTHS
    )
    + r"|Sept\.?"
)
_DATE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:(?:[-–]|\s+to\s+)(?P<last>\d{{1,2}}))?\s+(?P<month>{_MONTH})(?:\s+(?P<year>20\d{{2}}|19\d{{2}}))?(?!\w)",
    re.I,
)
_US_DATE = re.compile(
    rf"\b(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}})(?:,?\s+(?P<year>20\d{{2}}|19\d{{2}}))?\b",
    re.I,
)
_WORD = r"[A-ZÀ-Ý][\wÀ-ž’'-]*(?:\s+(?:[A-ZÀ-Ý][\wÀ-ž’'-]*|of|the|and|&)){0,4}"
_PLACE = re.compile(
    r"\b(?i:in and around|in|at|around|across(?: parts of| much of)?|near|struck|hit|"
    r"centred in|centered in|affected)\s+"
    r"(?i:(?:the\s+)?(?:(?:northern|southern|eastern|western|central|"
    r"northeastern|northwestern|southeastern|southwestern|neighbouring|"
    r"neighboring|nearby)\s+)?(?:(?:state|province|region|district|county|"
    rf"island)\s+of\s+)?)(?P<place>{_WORD})"
)
_WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
_WEEKDAY = re.compile(r"\b(" + "|".join(_WEEKDAYS) + r")\b", re.I)
_ADMINISTRATIVE_PLACE = re.compile(
    r"\b(?P<place>[A-ZÀ-Ý][\wÀ-ž’'-]*(?:(?:,\s*|\s+and\s+|\s+)[A-ZÀ-Ý][\wÀ-ž’'-]*)*"
    r"\s+(?:districts?|provinces?|states?|municipalit(?:y|ies)))\b",
)
_AFFECTED_ADMIN_GROUP = re.compile(
    rf"\b(?P<place>{_WORD}(?:,\s*{_WORD})*)\s+among\s+(?:the\s+)?"
    r"(?:hardest[- ]hit|worst[- ]affected|affected)\s+"
    r"(?:districts|provinces|municipalities)\b"
)
_STORM = re.compile(r"\b(?:Hurricane|Typhoon|Cyclone|Tropical Storm)\s+([A-Z][a-z]+)\b")
_VICTIM_ACTIVITY_NOTICE = (
    "The reported day identifies these victims' firefighting activity. "
    "It does not establish wildfire ignition or the start of the wider fire episode."
)


def _month_period(text: str) -> MentionTime | None:
    matches = [
        match
        for match in re.finditer(
            rf"\b(?P<month>{_MONTH})\s+(?P<year>(?:19|20)\d{{2}})\b",
            text,
            re.I,
        )
        if date_is_occurrence(text, match.start(), match.end())
    ]
    if len(matches) != 1:
        return None
    match = matches[0]
    year = int(match["year"])
    month = next(
        i + 1
        for i, name in enumerate(_MONTHS)
        if name[:3].casefold() == match["month"][:3].casefold()
    )
    return MentionTime(
        match[0],
        datetime(year, month, 1, tzinfo=UTC),
        datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC),
        "range",
    )


def _historical(text: str, source: SourceReference) -> bool:
    month = _month_period(text)
    dated_years = (
        int(match["year"])
        for pattern in (_DATE, _US_DATE)
        for match in pattern.finditer(text)
        if match["year"] and date_is_occurrence(text, match.start(), match.end())
    )
    return bool(
        re.search(
            r"\b(?:historical|anniversary|years? ago|last year|"
            r"previous event|similar to)\b",
            text,
            re.I,
        )
    ) or bool(
        source.published_at
        and (
            any(int(y) < source.published_at.year for y in occurrence_years(text))
            or any(year < source.published_at.year for year in dated_years)
            or (month and month.start and month.start.year < source.published_at.year)
        )
    )


def _time(text: str, source: SourceReference) -> MentionTime | None:
    matches = list(_DATE.finditer(text)) + list(_US_DATE.finditer(text))
    matches = [m for m in matches if date_is_occurrence(text, m.start(), m.end())]
    if not matches:
        month_period = _month_period(text)
        if month_period is not None:
            return month_period
        weekdays = [
            m
            for m in _WEEKDAY.finditer(text)
            if date_is_occurrence(text, m.start(), m.end())
        ]
        if len(weekdays) == 1:
            weekday = weekdays[0]
            if re.search(r"\b(?:next|every|each)\s*$", text[: weekday.start()], re.I):
                return None
            publication = source.published_at
            if publication is None or _historical(text, source):
                return MentionTime(weekday[0])
            target = next(
                i
                for i, name in enumerate(_WEEKDAYS)
                if name.casefold() == weekday[0].casefold()
            )
            days = (publication.weekday() - target) % 7
            if days == 0 and re.search(r"\blast\s*$", text[: weekday.start()], re.I):
                days = 7
            date = publication.date() - timedelta(days=days)
            if re.search(r"\blast week\b", text, re.I):
                monday = publication.date() - timedelta(days=publication.weekday())
                date = monday - timedelta(days=7) + timedelta(days=target)
            elif re.search(r"\bthis\s*$", text[: weekday.start()], re.I):
                monday = publication.date() - timedelta(days=publication.weekday())
                date = monday + timedelta(days=target)
                if date > publication.date():
                    return MentionTime(weekday[0])
            start = datetime(date.year, date.month, date.day, tzinfo=UTC)
            return MentionTime(
                weekday[0], start, start + timedelta(days=1), "day", True
            )
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
        if name[:3].casefold() == match["month"][:3].casefold()
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
    affected = _AFFECTED_ADMIN_GROUP.search(text)
    if affected:
        return MentionPlace(affected["place"], "named_place", "administrative_area")
    administrative = _ADMINISTRATIVE_PLACE.search(text)
    if administrative:
        value = re.sub(r"^In\s+", "", administrative["place"])
        words = value.split()
        if len(words) != 2 or words[0].casefold() not in {
            "the",
            "this",
            "that",
            "these",
            "those",
            "each",
            "a",
            "an",
            "several",
            "some",
        }:
            return MentionPlace(value, "named_place", "administrative_area")
    matches = [
        match
        for match in _PLACE.finditer(text)
        if not re.search(
            r"\b(?:based|headquartered|born|trained)\s*$", text[: match.start()], re.I
        )
    ]
    if not matches:
        return None
    # An explicit named location is descriptive until a geographic source resolves it.
    value = matches[0]["place"].strip(" ,.;:&")
    if value.endswith(("'s", "’s")):
        return None
    if value.casefold() in {month.casefold() for month in _MONTHS}:
        return None
    if value in {"The", "National", "Government", "October", "November"}:
        return None
    return MentionPlace(value, "named_place")


def _hazard_place(text: str, hazard: Disaster) -> MentionPlace | None:
    if hazard is Disaster.EARTHQUAKE:
        text = local_impact_context(text)
    clauses = re.split(r",\s*(?:as well as|whereas|while)\s+|;\s*", text, flags=re.I)
    matching = [clause for clause in clauses if disasters_in_text(clause) == (hazard,)]
    if len(clauses) > 1 and len(matching) == 1:
        return _place(matching[0])
    return _place(text)


def _report_text(text: str) -> str:
    offset = 0
    for part in source_sentences(text):
        start = text.index(part, offset)
        offset = start + len(part)
        sentence = part.strip(" •-\n")
        if not sentence:
            continue
        if re.fullmatch(
            r"related(?: news| stories| articles| content)\s*:?", sentence, re.I
        ) or (
            sentence.startswith("#")
            and re.fullmatch(
                r"(?:in the news|related(?: news| stories| articles| content)?|"
                r"what we.re reading|filed under|tags|media contacts|"
                r"additional resources|related topics|about .*)\s*:?",
                sentence.lstrip("# "),
                re.I,
            )
        ):
            return text[:start]
    return text


def _can_extend_detail(mention: EventMention, detail: str | None) -> bool:
    return detail is None or bool(
        mention.distinguishing_evidence
        and same_occurrence_detail(mention.distinguishing_evidence, detail)
    )


def _extract_section_mentions(
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
    title_country = (
        title_place.wording
        if title_place and title_place.wording.casefold() in country_names
        else None
    )
    # Markdown headings from report bodies are event context, never discarded markup.
    report_text = _report_text(text[:20_000])
    normalized = re.sub(
        r"\*\*([^*]+)\*\*",
        lambda m: f"\n{m[1]}\n" if m[1].isupper() and len(m[1]) < 100 else m[1],
        report_text,
    )
    # Titles such as Dr. must not become standalone heading-inherited mentions.
    sentences = [
        s.strip(" •-\n") for s in source_sentences(normalized) if s.strip(" •-\n")
    ]
    mentions: list[EventMention] = []
    active: list[int] = []
    heading_hazards: tuple[Disaster, ...] = ()
    heading_place: MentionPlace | None = None
    heading_names: tuple[str, ...] = ()
    for ordinal, sentence in enumerate(sentences):
        unresolved_scope = False
        fire_reference = None
        reference_place = None
        hazards = disasters_in_text(sentence)
        if not hazards and has_individual_aftershock(sentence):
            hazards = (Disaster.EARTHQUAKE,)
        if sentence.startswith("#"):
            heading_text = sentence.lstrip("# ")
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
        target = explicit_wildfire_reference_target(
            mentions, sentences[max(0, ordinal - 8) : ordinal], sentence
        )
        if target is not None:
            reference_time = _time(sentence, source)
            reference_place = _place(sentence)
            if reference_place is None and is_victim_firefighting_activity(sentence):
                reference_place = mentions[target].place
            prior_country = mentions[target].country_context
            prior_place = mentions[target].place
            if (
                prior_country is None
                and prior_place
                and prior_place.precision == "country_context"
            ):
                prior_country = prior_place.wording
            country_conflict = bool(
                reference_place
                and prior_country
                and prior_country.casefold() in country_names
                and reference_place.wording.casefold() in country_names
                and prior_country.casefold() != reference_place.wording.casefold()
            )
            prior_time = mentions[target].time
            if (
                reference_time
                and reference_time.start
                and reference_place
                and reference_place.precision == "named_place"
                and not country_conflict
                and occurrence_role(sentence, historical=_historical(sentence, source))
                == "reported"
                and (
                    prior_time is None
                    or (
                        prior_time.start == reference_time.start
                        and prior_time.end == reference_time.end
                    )
                )
            ):
                hazards = (Disaster.WILDFIRE,)
                fire_reference = target
        if not hazards:
            new_place = _place(sentence)
            target = local_context_target(mentions, active, new_place)
            if (
                target is not None
                and _time(sentence, source) is None
                and not _historical(sentence, source)
                and not has_distinct_occurrence(sentence)
                and occurrence_role(sentence) != "forecast"
            ):
                mention = mentions[target]
                mentions[target] = replace(mention, text=f"{mention.text} {sentence}")
                active = [target]
                continue
            if (
                active
                and new_place
                and all(
                    (
                        mentions[index].place is None
                        or mentions[index].place != new_place
                    )
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
        time = _time(sentence, source)
        if fire_reference is None and victim_activity_date_requires_reference(sentence):
            time = None
        names = tuple(dict.fromkeys(_STORM.findall(sentence))) or (
            heading_names if Disaster.TROPICAL_CYCLONE in hazards else ()
        )
        role = (
            "uncertain"
            if unresolved_scope
            else occurrence_role(sentence, historical=_historical(sentence, source))
        )
        felt_extent = hazards == (Disaster.EARTHQUAKE,) and is_felt_extent(sentence)
        if felt_extent:
            time = None
            role = "reported" if title_hazards == hazards and location else "uncertain"
        # One clause describing several hazards retains unallocated accounts as text.
        mixed = len(hazards) > 1 or len(names) > 1
        preceding_active = active
        active = []
        for hazard in hazards:
            detail = occurrence_detail(sentence)
            place = (
                MentionPlace(location, "country_context", "administrative_area")
                if felt_extent and location and title_hazards == hazards
                else None
                if felt_extent
                else _hazard_place(sentence, hazard)
            )
            if fire_reference is not None:
                place = reference_place
            if hazard is Disaster.DROUGHT and not re.search(
                r"\b(?:since|began|started|onset)\b", sentence, re.I
            ):
                time = None
            if (
                place is None
                and preceding_active
                and (
                    time is None or mentions[preceding_active[-1]].time in (None, time)
                )
                and not names
                and mentions[preceding_active[-1]].disaster == hazard
                and not mixed
                and not felt_extent
                and not has_distinct_occurrence(sentence)
                and not re.search(r"\b(?:across|throughout)\b", sentence, re.I)
            ):
                place = mentions[preceding_active[-1]].place
            place = place or heading_place
            if place is None and not mixed and title_hazards == (hazard,):
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
                and not felt_extent
                and not has_distinct_occurrence(sentence)
                and place is not None
                and not has_individual_aftershock(sentence)
                and _can_extend_detail(m, detail)
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
                and not felt_extent
                and not has_distinct_occurrence(sentence)
                and (place is None or previous.place == place)
                and not has_individual_aftershock(sentence)
                and _can_extend_detail(previous, detail)
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
                else location or title_country
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
                else (
                    "Felt-area references describe shaking reach. Unspecified "
                    "impact accounts retain the report country context; they are "
                    "not allocated to places where shaking was felt.",
                )
                if felt_extent
                else (),
                distinguishing_evidence=detail,
            )
            mentions.append(mention)
            activity_notices = (
                (_VICTIM_ACTIVITY_NOTICE,)
                if time and is_victim_firefighting_activity(sentence)
                else ()
            )
            if activity_notices:
                mentions[-1] = replace(
                    mentions[-1],
                    notices=(
                        *mentions[-1].notices,
                        *activity_notices,
                    ),
                )
            if fire_reference is not None:
                earlier = mentions[fire_reference]
                mentions[fire_reference] = replace(
                    earlier,
                    time=time,
                    occurrence_anchor_id=mention.mention_id,
                    notices=(
                        *earlier.notices,
                        "This article's explicit wildfire reference identifies the "
                        f"same physical occurrence: {sentence} Earlier impact "
                        "accounts retain their own reported geographic scope.",
                        *activity_notices,
                    ),
                )
            if time and time.start and _WEEKDAY.fullmatch(time.wording):
                mentions[-1] = replace(
                    mentions[-1],
                    notices=(
                        *mentions[-1].notices,
                        "Reported weekday resolved using article publication as "
                        "the reference and any explicit week wording. "
                        "Source wording is retained; "
                        "this is not an exact event time or known local timezone.",
                    ),
                )
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
                report_text,
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
                role=occurrence_role(report_text or source.title),
                notices=(
                    "Headline-only hazard context; event fields may remain unresolved.",
                ),
            )
        )
    result = []
    for mention in link_earthquake_country_accounts(
        attach_listed_place_periods(consolidate_local_context(mentions))
    )[:80]:
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
        if role == "historical":
            claims = tuple(
                replace(
                    claim,
                    qualifiers=tuple(dict.fromkeys((*claim.qualifiers, "historical"))),
                )
                for claim in claims
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
    return tuple(attach_hazard_episode_accounts(result, report_text, source))


def extract_mentions(
    text: str,
    source: SourceReference,
    *,
    location: str | None = None,
    event_time: datetime | None = None,
    geometry: EventGeometry | None = None,
    country_names: frozenset[str] = frozenset(),
) -> tuple[EventMention, ...]:
    """Keep explicitly independent publisher sections separate during association."""
    bounded = _report_text(text[:20_000])
    sections = re.split(r"\n##[ \t]*\n", bounded)
    if len(sections) == 1:
        return _extract_section_mentions(
            text,
            source,
            location=location,
            event_time=event_time,
            geometry=geometry,
            country_names=country_names,
        )
    eligible = [
        section
        for section in sections
        if disasters_in_text(section)
        and any(
            line.strip() and not line.lstrip().startswith("#")
            for line in section.splitlines()
        )
    ]
    result: list[EventMention] = []
    for index, section in enumerate(eligible[:80]):
        # Article-wide geometry and occurrence clocks do not identify an
        # independent subsection's event. Publication still anchors local weekdays.
        mentions = _extract_section_mentions(
            section, source, country_names=country_names
        )
        identities = {
            m.mention_id: "mention:"
            + hashlib.sha256(f"{m.mention_id}|section:{index}".encode()).hexdigest()[
                :24
            ]
            for m in mentions
        }
        result.extend(
            replace(
                mention,
                mention_id=identities[mention.mention_id],
                occurrence_anchor_id=identities.get(
                    mention.occurrence_anchor_id, mention.occurrence_anchor_id
                )
                if mention.occurrence_anchor_id
                else None,
            )
            for mention in mentions
        )
        if len(result) >= 80:
            break
    if len(result) > 80 or len(eligible) > 80:
        result = [
            replace(m, notices=(*m.notices, "Mention limit reached; source retained."))
            for m in result[:80]
        ]
    return tuple(result)
