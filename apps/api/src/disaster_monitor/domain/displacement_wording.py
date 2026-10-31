"""Separate explicit physical movement from source accounts of displaced people."""

import re

from disaster_monitor.domain.reported_number_wording import REPORTED_NUMBER

_PHYSICAL = (
    r"(?:sea\s*floor|sea\s*bed|ocean\s+floor|river\s*bed|"
    r"(?:tectonic\s+)?plates?|(?:Earth['’]s\s+)?crust|faults?|ground|"
    r"rocks?|boulders?|soil|sediments?|sand|water|lava|ice)"
)
_DETERMINERS = r"(?:(?:the|a|an|some|nearby|underlying|surrounding)\s+)*"
_POPULATION = (
    r"(?:people|persons?|residents?|families|households?|population|communities|"
    r"villagers?|inhabitants?|workers?|miners?|climbers?|farmers?|patients?|"
    r"men|women|children|others?)"
)
_PHYSICAL_DISPLACEMENT = (
    re.compile(rf"\b(?P<impact>displaced)\s+{_DETERMINERS}{_PHYSICAL}\b", re.I),
    re.compile(
        rf"\b{_PHYSICAL}\s+(?:(?:was|were|is|are|has|have|had|been|being|"
        r"got|reportedly|later|also|partially)\s+)+(?P<impact>displaced)\b",
        re.I,
    ),
    re.compile(
        rf"\b{_PHYSICAL}\s+(?:(?:horizontal|vertical|lateral)\s+)*"
        r"(?P<impact>displacement)\b",
        re.I,
    ),
    re.compile(
        rf"\b(?P<impact>displacement)\s+(?:of|on|along|within)\s+"
        rf"{_DETERMINERS}{_PHYSICAL}\b",
        re.I,
    ),
)
_HUMAN_DISPLACEMENT = re.compile(
    r"\b(?:human|population|civilian|community|household|resident)\s+$", re.I
)
_COORDINATED_POPULATION = re.compile(
    rf"^\s*(?:,\s*(?:and\s+)?|(?:and|as\s+well\s+as)\s+)"
    rf"(?:(?:the|some|{REPORTED_NUMBER})\s+)*{_POPULATION}\b",
    re.I,
)
_HUMAN_HEAD = re.compile(rf"^(?:\s+|[-–]){_POPULATION}\b", re.I)
_OTHER_POPULATION_ACCOUNT = re.compile(
    r"^\s+(?:(?:were|was|are|is|have|has|had|been|being|reportedly|also)\s+)*"
    r"(?:injured|wounded|hurt|died|dead|killed|missing|rescued|hospitali[sz]ed)\b",
    re.I,
)


def displacement_analysis_text(text: str) -> str:
    """Mask explicit nonhuman predicates, retaining offsets and other claims."""
    masked = list(text)
    for pattern in _PHYSICAL_DISPLACEMENT:
        for match in pattern.finditer(text):
            start, end = match.span("impact")
            following = text[match.end() :]
            population = _COORDINATED_POPULATION.search(following)
            shared_population = population is not None and not (
                _OTHER_POPULATION_ACCOUNT.search(following[population.end() :])
            )
            # A shared predicate may govern both objects, or a physical noun may
            # modify a human head such as 'water workers'. Keep that ambiguity.
            if (
                _HUMAN_DISPLACEMENT.search(text[:start])
                or shared_population
                or _HUMAN_HEAD.search(following)
            ):
                continue
            masked[start:end] = " " * (end - start)
    return "".join(masked)
