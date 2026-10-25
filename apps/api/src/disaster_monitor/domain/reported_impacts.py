"""Conservative attributed impact extraction, separate from fact reconciliation.

These are source accounts, never totals or verified facts. The supporting sentence
retains dates, scopes, overlap, and qualifications that cannot safely be normalized.
"""

import re
from dataclasses import dataclass

from disaster_monitor.domain.evidence import ReportedFact, SituationReport
from disaster_monitor.domain.evidence_types import FactStatus, SourceReference
from disaster_monitor.domain.nonhuman_impact_wording import (
    has_nonhuman_death_wording,
    has_possible_human_referent,
    nonhuman_death_sentences,
)
from disaster_monitor.domain.regional_accounts import (
    mask_german_articles,
    regional_fatality_account,
)
from disaster_monitor.domain.reported_number_wording import (
    REPORTED_NUMBER,
    comparable_reported_number,
    is_approximate_reported_number,
)
from disaster_monitor.domain.source_sentences import (
    source_analysis_text,
    source_sentences,
)

IMPACT_LABELS = {
    "fatalities": "Fatalities",
    "injuries": "Injuries",
    "displacement": "Displacement",
    "roads_bridges": "Roads and bridges",
    "electricity": "Electricity networks",
    "water": "Water systems",
    "communications": "Communications networks",
}
_TERMS = {
    "fatalities": (
        r"died|dies?|dead|killed|(?<!-)killing|drowned|deaths?|fatalities|death toll|"
        r"claimed the lives of|took the lives of"
    ),
    "injuries": r"injured|injuries|wounded",
    "displacement": r"displaced|displacement|homeless",
    "roads_bridges": r"roads?|bridges?|highways?",
    "electricity": r"electricity|power (?:grid|lines?|networks?|suppl\w+)",
    "water": (
        r"water (?:systems?|networks?|suppl\w+|pipes?|"
        r"(?:and [a-z]+ ){0,2}infrastructure)"
    ),
    "communications": (
        r"communications? (?:networks?|systems?)|telecom\w*|phone networks?"
    ),
}
_HUMAN_IMPACT_TERMS = "|".join(
    _TERMS[category] for category in ("fatalities", "injuries", "displacement")
)
_NUMBER = REPORTED_NUMBER
_PERSON = (
    r"(?:(?-i:[A-ZÀ-Ý][\wÀ-ž'-]*)\s+){0,2}"
    r"(?:people|persons?|men|women|children|residents|soldiers?|others?|"
    r"firefighters?|workers?|miners?|volunteers?|responders?|passengers?|"
    r"boys?|girls?|babies|infants?|counsel(?:l)?ors?|campers?)"
)
_PERSON_GROUP = rf"{_PERSON}(?:\s+(?:and|plus)\s+{_PERSON})*"
_LINK = (
    rf"(?:\s+of\s+(?:the\s+)?(?:{_NUMBER}\s+)?{_PERSON_GROUP})?"
    rf"(?:\s+(?:{_PERSON_GROUP}|were|was|are|is|"
    r"have|has|been|being|had|reportedly|may|might|confirmed|reported|at|least|about|"
    r"approximately|temporarily|internally|newly))*\s+"
)
_COUNTED_POPULATION = (
    rf"(?:{_NUMBER}|a|an|the)\s+"
    r"(?:of\s+)?"
    r"(?:(?:youth|camp|adult|young)\s+)?"
    rf"(?:{_PERSON}|reservists?|counsel(?:l)?ors?|campers?|owners?|adults?)"
)
_POPULATION_LIST = (
    rf"{_COUNTED_POPULATION}"
    rf"(?:\s*,\s*(?:(?:and|plus)\s+)?|\s+(?:and|plus)\s+)"
    rf"{_COUNTED_POPULATION}"
)
_HUMAN_REFERENT = re.compile(
    rf"\b(?:{_PERSON}|farmers?|herders?|ranchers?|boys?|girls?|babies?|adults?|victims?)\b",
    re.I,
)
_ABSENT_REPORTING = re.compile(
    r"\bno\s+(?:(?:confirmed|known|official)\s+)?reports?\s+of\b", re.I
)
_NONFATAL_DROWNING = re.compile(
    r"\b(?:(?:nearly|almost|feared|presumed)\s+"
    r"(?:(?:to|be|have|been|had)\s+){0,3}drowned|"
    r"(?:believed|thought)\s+to\s+have\s+drowned|"
    r"drowned(?=\s+(?:but|and)\s+"
    r"(?:(?:was|were|have|had|been|both|all|successfully)\s+){0,5}"
    r"(?:resuscitated|revived|survived)\b))\b",
    re.I,
)
_PREDICTED_DEATH = re.compile(
    r"\b(?:going\s+to|will)\s+(?:(?:not|never)\s+)?"
    r"(?:be\s+)?(?:die|dead|killed|drowned)\b",
    re.I,
)
_POPULATION_COMPARISON = re.compile(
    r"\bwould\s+be\s+(?:comparable|equivalent)\s+to\b"
    r"[^.!?;\n]{0,100}\b(?:deaths?|fatalities)\b[^.!?;\n]{0,60}"
    r"\b(?:today(?:['’]s)?|(?:current|modern)\s+population)\b",
    re.I,
)
_BURN_ACCOUNT = re.compile(
    rf"\b(?:(?P<count>{_NUMBER}|no)\s+)?"
    rf"(?:{_PERSON}|firefighters?|responders?|volunteers?|patients?|victims?)"
    r"\s+(?:(?:had|have|has|reportedly)\s+)*"
    r"(?:suffered|sustained)\s+(?:(?:severe|serious|minor|extensive|"
    r"first-degree|second-degree|third-degree)\s+)*burns\b",
    re.I,
)
_CALENDAR_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DAMAGE = re.compile(
    r"\b(?:damag\w*|destroy\w*|disrupt\w*|collaps\w*|washed away|"
    r"outage\w*|block\w*|down|cut off|unaffected|intact)\b",
    re.I,
)
_QUALIFIERS = {
    "temporary": r"\btemporar(?:y|ily)\b",
    "preliminary": r"\b(?:preliminary|initial|early reports)\b",
    "corrected": r"\b(?:correct\w*|revised|revision)\b",
    "historical": (
        r"\b(?:last year|years? ago|historical|anniversary|previous disaster)\b"
    ),
    "uncertain": (
        r"\b(?:may|might|unconfirmed|uncertain|estimated|at least|about|"
        r"approximately|reportedly|denied|false)\b"
    ),
}


@dataclass(frozen=True, slots=True)
class ReportedImpact:
    fact: ReportedFact
    excerpt: str
    qualifiers: tuple[str, ...] = ()


def only_nonhuman_deaths(text: str) -> bool:
    """Explicit nonhuman death wording without a possible human account."""
    return has_nonhuman_death_wording(text) and not has_possible_human_referent(
        text, _HUMAN_REFERENT
    )


def nonhuman_fatality_sentences(text: str) -> frozenset[str]:
    """Identify nonhuman accounts before hazard scoping removes antecedents."""
    return nonhuman_death_sentences(text, _HUMAN_REFERENT)


def fatality_analysis_text(
    text: str, *, nonhuman_sentences: frozenset[str] = frozenset()
) -> str:
    """Mask nonfatal and predicted deaths at original source offsets."""
    # Mention construction can join a quoted source sentence to its next line.
    # Mask only the original nonhuman span, preserving any later human account.
    for sentence in nonhuman_sentences:
        text = text.replace(sentence, " " * len(sentence))
    analysis = mask_german_articles(source_analysis_text(text))
    for pattern in (_NONFATAL_DROWNING, _PREDICTED_DEATH, _POPULATION_COMPARISON):
        analysis = pattern.sub(lambda match: " " * len(match[0]), analysis)
    return analysis


def _context_count(sentence: str, match: re.Match[str]) -> bool:
    value = match[1].replace(",", "")
    if not value.isdigit():
        return False
    before, after = sentence[: match.start(1)], sentence[match.end(1) :]
    return bool(
        re.match(r"[-\s]+(?:years?|months?|days?|hours?)[-\s]+old\b", after, re.I)
        or re.search(rf"\b{_CALENDAR_MONTH}\.?\s*$", before, re.I)
        or re.match(rf"\s+{_CALENDAR_MONTH}\b", after, re.I)
        or (
            len(value) == 4
            and 1900 <= int(value) <= 2100
            and re.search(r"\b(?:in|during|since)\s*$", before, re.I)
        )
    )


def _coordinated_impact_populations(analysis: str, terms: str) -> bool:
    """A casualty predicate governing a list does not allocate one component total."""
    return bool(
        re.search(
            rf"\b(?:{terms})\s+(?:{_POPULATION_LIST})\b|"
            rf"\b(?:{_POPULATION_LIST}){_LINK}(?:{terms})\b",
            analysis,
            re.I,
        )
    )


def inspect_report_impacts(report: SituationReport) -> tuple[ReportedImpact, ...]:
    """Project all in-scope provider facts, retaining their own source accounts."""
    accounts = []
    extracted = extract_reported_impacts(report.narrative, report.source)
    for fact in report.facts:
        identity = f"{fact.category} {fact.label}".replace("_", " ")
        if re.search(
            r"\b(?:schools?|hospitals?|property|homes?|buildings?|monetary|economic)\b",
            identity,
            re.I,
        ):
            continue
        categories = {
            category
            for category, terms in _TERMS.items()
            if re.search(rf"\b(?:{terms})\b", identity, re.I)
        }
        if not categories:
            continue
        supporting = next(
            (
                claim
                for claim in extracted
                if claim.fact.category in categories
                and fact.source.canonical_url == report.source.canonical_url
                and _account_value(claim.fact.value) == _account_value(fact.value)
            ),
            None,
        )
        accounts.append(
            ReportedImpact(
                fact,
                supporting.excerpt if supporting else "",
                tuple(
                    dict.fromkeys(
                        (
                            fact.status.value,
                            *(supporting.qualifiers if supporting else ()),
                        )
                    )
                ),
            )
        )
    return tuple(accounts)


def _account_value(value: str) -> str:
    return comparable_reported_number(value)


def _burn_injury_accounts(
    sentence: str,
    source: SourceReference,
    location: str | None,
    qualifiers: tuple[str, ...],
) -> tuple[ReportedImpact, ...]:
    """Keep explicit personal burns separate from any broader injury count."""
    accounts = []
    for match in _BURN_ACCOUNT.finditer(sentence):
        count = match["count"]
        value = (
            "Reported; count unknown"
            if count is None
            else "0"
            if count.casefold() == "no"
            else count.replace(",", "")
        )
        accounts.append(
            ReportedImpact(
                ReportedFact(
                    "injuries",
                    "Burn injuries",
                    value,
                    FactStatus.PRELIMINARY
                    if "preliminary" in qualifiers
                    else FactStatus.UNKNOWN,
                    source,
                    reported_location=location,
                ),
                sentence,
                qualifiers,
            )
        )
    return tuple(accounts)


def extract_reported_impacts(
    text: str,
    source: SourceReference,
    *,
    location: str | None = None,
    source_context: str | None = None,
) -> tuple[ReportedImpact, ...]:
    claims = []
    nonhuman_sentences = nonhuman_fatality_sentences(
        text if source_context is None else source_context
    )
    for sentence in source_sentences(text[:20_000]):
        sentence = sentence.strip()
        # Do not cut a long source sentence and imply its qualification survived.
        if not sentence or len(sentence) > 600:
            continue
        visible_sentence = source_analysis_text(sentence)
        sentence_qualifiers = tuple(
            k
            for k, pattern in _QUALIFIERS.items()
            if re.search(pattern, visible_sentence, re.I)
        )
        fatality_sentence = fatality_analysis_text(
            sentence, nonhuman_sentences=nonhuman_sentences
        )
        for category, terms in _TERMS.items():
            qualifiers = sentence_qualifiers
            analysis = (
                fatality_sentence if category == "fatalities" else visible_sentence
            )
            if not re.search(rf"\b(?:{terms})\b", analysis, re.I):
                continue
            nonhuman_deaths = category == "fatalities" and has_nonhuman_death_wording(
                analysis
            )
            if category == "fatalities" and (
                sentence in nonhuman_sentences or only_nonhuman_deaths(analysis)
            ):
                continue
            value = "Unknown"
            if category in ("fatalities", "injuries", "displacement"):
                alternatives = bool(
                    re.search(r"\beither\b.+\bor\b|\bdead or missing\b", analysis, re.I)
                )
                absent_reporting = bool(_ABSENT_REPORTING.search(analysis))
                if alternatives or absent_reporting:
                    qualifiers = tuple(dict.fromkeys((*qualifiers, "uncertain")))
                before_counts = tuple(
                    match
                    for match in re.finditer(
                        rf"\b({_NUMBER}){_LINK}(?:{terms})\b", analysis, re.I
                    )
                    if not _context_count(analysis, match)
                )
                after_counts = tuple(
                    match
                    for match in re.finditer(
                        rf"\b(?:{terms})\s+(?:(?:rose|risen|stands|stood|increased|reported|was|were|is|at|to|of|least)\s+)*({_NUMBER})\b",
                        analysis,
                        re.I,
                    )
                    if not _context_count(analysis, match)
                )
                zero = re.search(
                    rf"\b(?:no|zero|without)(?:\s+(?:one|any))?{_LINK}"
                    rf"(?:(?:{_HUMAN_IMPACT_TERMS})\s+(?:or|nor)\s+)*"
                    rf"(?:{terms})\b",
                    analysis,
                    re.I,
                )
                counts = (*before_counts, *after_counts)
                count = next(iter(counts), None)
                unresolved_counts = len(
                    {_account_value(match[1]) for match in counts}
                ) > 1 or _coordinated_impact_populations(analysis, terms)
                if alternatives or absent_reporting:
                    value = "Unknown"
                elif unresolved_counts:
                    qualifiers = tuple(
                        dict.fromkeys((*qualifiers, "uncertain", "scope unresolved"))
                    )
                elif (
                    zero
                    and count
                    and count[1].casefold() not in ("0", "zero")
                    and not zero.start() <= count.start() < zero.end()
                ):
                    qualifiers = tuple(
                        dict.fromkeys((*qualifiers, "uncertain", "scope unresolved"))
                    )
                elif zero:
                    value = "0"
                elif count:
                    value = count[1].replace(",", "")
                elif not re.search(
                    r"\b(?:unknown|unconfirmed|unclear|"
                    r"not (?:yet )?(?:known|reported|available))\b",
                    visible_sentence,
                    re.I,
                ):
                    # A qualitative account remains visible without a count.
                    value = "Reported; count unknown"
            else:
                if not _DAMAGE.search(sentence):
                    continue
                value = "Source account"
            status = (
                FactStatus.PRELIMINARY
                if "preliminary" in qualifiers
                else FactStatus.UNKNOWN
            )
            claim_qualifiers = qualifiers
            if is_approximate_reported_number(value):
                claim_qualifiers = tuple(
                    dict.fromkeys((*qualifiers, "approximate", "uncertain"))
                )
            if nonhuman_deaths:
                value = "Unknown"
                claim_qualifiers = tuple(
                    dict.fromkeys((*qualifiers, "uncertain", "scope unresolved"))
                )
            claims.append(
                ReportedImpact(
                    ReportedFact(
                        category,
                        IMPACT_LABELS[category],
                        value,
                        status,
                        source,
                        reported_location=location,
                    ),
                    sentence,
                    claim_qualifiers,
                )
            )
        if not re.search(rf"\b(?:{_TERMS['fatalities']})\b", fatality_sentence, re.I):
            regional = regional_fatality_account(visible_sentence)
            if regional is not None:
                qualified = tuple(dict.fromkeys((*qualifiers, *regional.qualifiers)))
                claims.append(
                    ReportedImpact(
                        ReportedFact(
                            "fatalities",
                            IMPACT_LABELS["fatalities"],
                            regional.value,
                            FactStatus.PRELIMINARY
                            if "preliminary" in qualified
                            else FactStatus.UNKNOWN,
                            source,
                            reported_location=location,
                        ),
                        sentence,
                        qualified,
                    )
                )
        claims.extend(
            _burn_injury_accounts(sentence, source, location, sentence_qualifiers)
        )
    return tuple(claims)
