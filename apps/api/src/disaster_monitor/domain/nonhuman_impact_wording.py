"""Shared wording for distinguishing nonhuman losses from human accounts."""

import re

from disaster_monitor.domain.reported_number_wording import REPORTED_NUMBER
from disaster_monitor.domain.source_sentences import (
    source_analysis_text,
    source_sentences,
)

NONHUMAN_TERMS = (
    r"cows?|cattle|livestock|animals?|sheep|goats?|horses?|dogs?|cats?|pigs?|poultry|"
    r"buffalo(?:es)?|donkeys?|equids?|alpacas?|llamas?|trees?|plants?|crops?|"
    r"forested lands?|"
    r"vacas?|ganado|animales?|ovejas?|cabras?|caballos?|perros?|reses|peces|aves|"
    r"vaches?|b[eê]tail|animaux|moutons?|ch[eè]vres?|chevaux|chiens?|"
    r"sapi|ternak|hewan|kambing|domba|anjing|kucing|"
    r"animais|gado|bovinos?|cães|gatos?|[aá]rvores?|plantas?|"
    r"inek(?:ler)?|hayvan(?:lar)?|köpek(?:ler)?|ağaç(?:lar)?|"
    r"Kühe|Kuh|Rinder|Tiere|Hunde|Katzen|Bäume"
)
_NONHUMAN = re.compile(rf"(?:{NONHUMAN_TERMS})", re.I)
_WEATHER_NAME = re.compile(
    r"\b(?:fen[oó]meno\s+(?:(?:clim[aá]tico|de)\s+)?"
    r"(?:El\s+Niño|La\s+Niña)|"
    r"(?:El\s+Niño|La\s+Niña)\s+(?:weather\s+pattern|phenomenon))\b",
    re.I,
)
_NAME = r"[A-ZÀ-ÖØ-Þ][\wÀ-ž'’-]*"
_COORDINATOR = r"(?i:and|y|et|dan|e|ve|und)"
_NONHUMAN_MEMBER = rf"(?i:(?:[\wÀ-ž,.]+\s+){{0,3}}(?:{NONHUMAN_TERMS}))"
_COORDINATED_NAME = re.compile(
    rf"\b(?P<before>{_NAME})\s+{_COORDINATOR}\s+{_NONHUMAN_MEMBER}\b|"
    rf"\b(?i:{NONHUMAN_TERMS})\s+{_COORDINATOR}\s+(?P<after>{_NAME})\b"
)
_DEATH = r"died|dies?|dead|killed|drowned|deaths?|fatalities"
_AUXILIARY = (
    r"(?:(?:were|was|are|is|have|had|has|been|being|also|reportedly|"
    r"found|reported|to)\s+)*"
)
_NONHUMAN_DEATH = re.compile(
    rf"\b(?:{NONHUMAN_TERMS})\s+{_AUXILIARY}(?:{_DEATH})\b|"
    rf"\b(?:killed|(?<!-)killing|drowned|dead|deaths? of)\s+"
    rf"(?:(?:{REPORTED_NUMBER})\s+)?(?:of\s+)?(?:{NONHUMAN_TERMS})\b",
    re.I,
)
_PRONOUN_DEATH = re.compile(rf"^\W*(?:they|it)\s+{_AUXILIARY}(?:{_DEATH})\b", re.I)
_DEATH_PREDICATE = re.compile(rf"\b(?:{_DEATH})\b", re.I)
_ADDITIONAL_MEMBER = re.compile(r"\b(?:with|including|as well as)\b", re.I)


def has_nonhuman_death_wording(text: str) -> bool:
    """Detect an explicit nonhuman loss, including mixed human/animal accounts."""
    return bool(_NONHUMAN_DEATH.search(text))


def nonhuman_death_sentences(text: str, human_terms: re.Pattern[str]) -> frozenset[str]:
    """Keep one immediate nonhuman antecedent; never bridge headings or gaps.

    An unresolved pronoun remains an account. Human referents, mixed victims and
    multiple death predicates prevent treating a whole sentence as nonhuman.
    Identical wording with another unresolved referent stays unresolved. Returned
    source sentences are unchanged, so claim excerpts retain provenance.
    """
    occurrences: dict[str, list[bool]] = {}
    previous = ""
    bounded = text[:20_000]
    for original in source_sentences(bounded):
        sentence = original.strip()
        analysis = source_analysis_text(sentence)
        possible_human = has_possible_human_referent(analysis, human_terms)
        explicit = has_nonhuman_death_wording(analysis) and not possible_human
        pronoun = (
            _PRONOUN_DEATH.search(analysis)
            and len(_DEATH_PREDICATE.findall(analysis)) == 1
            and not _ADDITIONAL_MEMBER.search(analysis)
            and not possible_human
            and has_nonhuman_death_wording(previous)
            and not has_possible_human_referent(previous, human_terms)
        )
        occurrences.setdefault(sentence, []).append(bool(explicit or pronoun))
        previous = (
            analysis
            if sentence and len(sentence) <= 600 and not sentence.startswith("#")
            else ""
        )
    return frozenset(
        sentence
        for sentence, classifications in occurrences.items()
        if sentence
        and all(classifications)
        and bounded.count(sentence) == len(classifications)
    )


def has_possible_human_referent(text: str, human_terms: re.Pattern[str]) -> bool:
    """Keep explicit people and ambiguous named members of a coordinated toll.

    A capitalized coordinated name is only a reason not to discard an account;
    it never establishes a human count. Explicit weather names are not people.
    """
    analysis = _WEATHER_NAME.sub(lambda match: " " * len(match[0]), text)
    if human_terms.search(analysis):
        return True
    return any(
        not _NONHUMAN.fullmatch(match["before"] or match["after"])
        for match in _COORDINATED_NAME.finditer(analysis)
    )
