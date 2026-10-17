"""Conservative English claim extraction, separate from selected-fact reconciliation.

These are source accounts, never totals or verified facts. The supporting sentence
retains dates, scopes, overlap, and qualifications that cannot safely be normalized.
"""

import re
from dataclasses import dataclass

from disaster_monitor.domain.evidence import ReportedFact, SituationReport
from disaster_monitor.domain.evidence_types import FactStatus, SourceReference

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
    "fatalities": r"died|dead|killed|deaths?|fatalities|death toll",
    "injuries": r"injured|injuries|wounded",
    "displacement": r"displaced|displacement|homeless",
    "roads_bridges": r"roads?|bridges?|highways?",
    "electricity": r"electricity|power (?:grid|lines?|networks?|suppl\w+)",
    "water": r"water (?:systems?|networks?|suppl\w+|pipes?)",
    "communications": (
        r"communications? (?:networks?|systems?)|telecom\w*|phone networks?"
    ),
}
_NUMBER = (
    r"(?:\d[\d,]*|zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"dozens|hundreds|thousands)"
)
_LINK = (
    r"(?:\s+(?:people|persons?|men|women|children|residents|were|was|are|is|"
    r"have|has|been|had|reportedly|may|might|confirmed|reported|at|least|about|"
    r"approximately))*\s+"
)
_DAMAGE = re.compile(
    r"\b(?:damag\w*|destroy\w*|disrupt\w*|collaps\w*|washed away|"
    r"outage\w*|down|cut off|unaffected|intact)\b",
    re.I,
)
_QUALIFIERS = {
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
    normalized = value.strip().casefold().replace(",", "")
    words = "zero one two three four five six seven eight nine ten".split()
    return str(words.index(normalized)) if normalized in words else normalized


def extract_reported_impacts(
    text: str,
    source: SourceReference,
    *,
    location: str | None = None,
) -> tuple[ReportedImpact, ...]:
    claims = []
    for sentence in re.split(r"(?<=[.!?])\s+", text[:20_000]):
        sentence = sentence.strip()
        # Do not cut a long source sentence and imply its qualification survived.
        if not sentence or len(sentence) > 600:
            continue
        qualifiers = tuple(
            k
            for k, pattern in _QUALIFIERS.items()
            if re.search(pattern, sentence, re.I)
        )
        for category, terms in _TERMS.items():
            if not re.search(rf"\b(?:{terms})\b", sentence, re.I):
                continue
            value = "Unknown"
            if category in ("fatalities", "injuries", "displacement"):
                before = re.search(
                    rf"\b({_NUMBER}){_LINK}(?:{terms})\b", sentence, re.I
                )
                after = re.search(
                    rf"\b(?:{terms})\s+(?:(?:rose|risen|stands|stood|increased|reported|was|were|is|at|to|of|least)\s+)*({_NUMBER})\b",
                    sentence,
                    re.I,
                )
                zero = re.search(
                    rf"\b(?:no|zero)(?:\s+one)?{_LINK}(?:{terms})\b", sentence, re.I
                )
                count = before or after
                if zero:
                    value = "0"
                elif count:
                    value = count[1].replace(",", "")
                elif not re.search(
                    r"\b(?:unknown|unconfirmed|unclear|"
                    r"not (?:yet )?(?:known|reported|available))\b",
                    sentence,
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
                    qualifiers,
                )
            )
    return tuple(claims)
