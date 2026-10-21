"""Source-preserving English sentence boundaries for attributed extraction."""

import re

# Periods in month and personal-title abbreviations are not sentence boundaries.
_NOT_ABBREVIATION = "".join(
    rf"(?<!\b{re.escape(word)}\.)"
    for word in (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Sept",
        "Oct",
        "Nov",
        "Dec",
        "Dr",
        "Mr",
        "Mrs",
        "Ms",
        "a.m",
        "p.m",
    )
)
_SENTENCE = _NOT_ABBREVIATION + r"(?<=[.!?])\s+"
_CLAUSE = _NOT_ABBREVIATION + r"(?<=[.])(?=\s)|[!?;–—]"


def source_sentences(text: str) -> list[str]:
    return re.split(_SENTENCE + r"|\n+|\s+[•]\s+|\s+-\s+", text, flags=re.I)


def source_clauses(text: str) -> list[str]:
    return re.split(_CLAUSE, text, flags=re.I)
