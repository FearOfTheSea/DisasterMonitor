"""Mask explicit nonliteral cues without erasing other literal hazard wording."""

import re

_LANDSLIDE_AREA = r"(?!\s+(?:zones?|areas?|debris|deposits|prone)\b)"
_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\b(?:won|wins?|winning|defeat(?:ed|s)?)\b"
        r"(?:[ \t]+[\w’'-]+){0,8}?[ \t]+(?:by|in)[ \t]+"
        r"(?:an?[ \t]+)?(?P<hazard>landslides?)\b" + _LANDSLIDE_AREA,
        r"\b(?P<hazard>landslides?)\s+(?:victor(?:y|ies)|wins?|"
        r"election\s+results?)\b",
        r"\b(?:electoral|political)\s+(?P<hazard>landslides?)\b",
        r"\b(?:pain|memories|emotions|feelings)\b"
        r"(?:[ \t]+[\w’'-]+){0,10}[ \t]+(?:came|come|comes|coming)[ \t]+"
        r"(?P<hazard>flooding)[ \t]+back\b",
        r"\b(?P<hazard>flood)\s+the\s+zone\s+with\s+"
        r"(?:(?:our|their|your|my|own|more)\s+){0,4}people\b",
        r"\b(?P<hazard>earthquake)(?=(?:['’]s)?\s+"
        r"(?:[A-Z]\d[\w-]*\s+)?wood[ -]?chippers?\b)",
        r"\b(?P<hazard>seismic)(?=\s+"
        r"(?:surveys?|surveying|campaigns?|exploration|acquisition)\b)",
        r"\b(?P<hazard>seismic)(?=\s+and\s+G&G(?:\s+(?:costs?|expenses?)|"
        r",\s*land,\s*capitalized)\b)",
        r"\b(?P<hazard>earthquake)(?=\s+and\s+tsunami\s+"
        r"(?:geology\s+)?team\b)",
        r"\b(?:Ebola|cholera|disease)\b"
        r"[^.!?;\n]{0,100}?\blike\s+(?:(?:fighting|a|an)\s+){0,2}"
        r"(?P<hazard>wildfire)\b",
    )
)
_RELATED_LINK = re.compile(r"^[ \t]*READ MORE\s*:\s*[^\n]{1,240}(?=\n|$)", re.I | re.M)


def _mask_hazard(match: re.Match[str]) -> str:
    start, end = match.span("hazard")
    start, end = start - match.start(), end - match.start()
    return match[0][:start] + " " * (end - start) + match[0][end:]


def mask_nonliteral_hazard_context(text: str) -> str:
    """Keep offsets and any separate literal occurrence in the same source."""
    text = _RELATED_LINK.sub(lambda match: " " * len(match[0]), text)
    for pattern in _PATTERNS:
        text = pattern.sub(_mask_hazard, text)
    return text
