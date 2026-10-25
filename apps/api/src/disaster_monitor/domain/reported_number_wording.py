"""Whole English source count expressions and equivalence for repeated accounts.

The original expression is displayed. Numeric equivalence only compares repeated
counts; it never adds source accounts or estimates a population.
"""

import re

_ONES = "one two three four five six seven eight nine".split()
_SMALL = "zero one two three four five six seven eight nine ten eleven twelve "
_SMALL += "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_JOIN = r"[\s\u2010-\u2015-]+"
_BELOW_HUNDRED = (
    rf"(?:(?:{'|'.join(_TENS)})(?:{_JOIN}(?:{'|'.join(_ONES)}))?|"
    rf"(?:{'|'.join(_SMALL.split())}))"
)
_HUNDREDS = (
    rf"(?:{'|'.join(_ONES)}|a){_JOIN}hundred"
    rf"(?:\s+(?:and\s+)?{_BELOW_HUNDRED})?"
)
_CHUNK = rf"(?:(?:\d{{1,3}}(?:,\d{{3}})+|\d+)|{_HUNDREDS}|{_BELOW_HUNDRED})"
_CARDINAL = (
    rf"{_CHUNK}(?:\s+(?:billion|million|thousand)"
    rf"(?:\s+(?:and\s+)?{_CHUNK})?){{0,3}}"
)
_APPROXIMATE_UNIT = r"(?:dozens|scores|tens|hundreds|thousands|millions|billions)"
_APPROXIMATE = rf"{_APPROXIMATE_UNIT}(?:\s+of\s+{_APPROXIMATE_UNIT}){{0,2}}"
REPORTED_NUMBER = (
    # Never start inside a compound or decimal that the grammar cannot retain.
    rf"(?<![\w.,\u2010-\u2015-])(?:{_CARDINAL}|{_APPROXIMATE})"
    r"(?!\w|[.,]\d)"
)
_CARDINAL_FULL = re.compile(rf"{_CARDINAL}", re.I)
_APPROXIMATE_FULL = re.compile(_APPROXIMATE, re.I)
_VALUES = {word: number for number, word in enumerate(_SMALL.split())}
_VALUES.update({word: number * 10 for number, word in enumerate(_TENS, 2)})
_VALUES["a"] = 1
_SCALES = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def is_approximate_reported_number(value: str) -> bool:
    """Recognize vague source counts without assigning a numeric estimate."""
    return bool(_APPROXIMATE_FULL.fullmatch(value.strip()))


def comparable_reported_number(value: str) -> str:
    """Compare explicit English cardinals without rewriting source wording."""
    normalized = value.strip().casefold().replace(",", "")
    if not _CARDINAL_FULL.fullmatch(normalized):
        return normalized
    total = chunk = 0
    previous_scale = 1_000_000_001
    for word in re.split(_JOIN, normalized):
        if word == "and":
            continue
        if word == "hundred":
            chunk = (chunk or 1) * 100
        elif word in _SCALES:
            if _SCALES[word] >= previous_scale:
                # Nonstandard compound scales retain wording, not a guessed value.
                return normalized
            previous_scale = _SCALES[word]
            total += chunk * _SCALES[word]
            chunk = 0
        else:
            chunk += int(word) if word.isdigit() else _VALUES[word]
    return str(total + chunk)
