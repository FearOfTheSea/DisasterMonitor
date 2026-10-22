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
_INLINE_CITATION = re.compile(r"\[([^\]\n]{1,600})\]\([^\n)]{1,2048}\)")


def source_analysis_text(text: str) -> str:
    """Keep citation labels, masking presentation and targets at original offsets."""
    return _INLINE_CITATION.sub(
        lambda match: " " + match[1] + " " * (len(match[0]) - len(match[1]) - 1), text
    )


def source_sentences(text: str) -> list[str]:
    return re.split(_SENTENCE + r"|\n+|\s+[•]\s+|\s+-\s+", text, flags=re.I)


def source_clauses(text: str) -> list[str]:
    return re.split(_CLAUSE, text, flags=re.I)
