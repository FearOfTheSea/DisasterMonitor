"""Provider-text normalization at the adapter boundary."""

import re
from html import unescape

MAX_NARRATIVE_LENGTH = 1_200
_TAG = re.compile(r"<[^>]+>")
_INSTRUCTION_FRAGMENT = re.compile(
    r"\b(?:ignore|disregard|override|system message|developer message|"
    r"tool call|prompt injection)(?:\s+\w+){0,4}[.!?:;]?",
    re.IGNORECASE,
)


def sanitize_provider_text(text: str, *, limit: int = MAX_NARRATIVE_LENGTH) -> str:
    """Remove markup, control characters, and instruction-like provider text."""
    cleaned = _TAG.sub(" ", unescape(text))
    lines = []
    for line in cleaned.splitlines():
        safe_line = _INSTRUCTION_FRAGMENT.sub(" ", line)
        safe_line = re.sub(r"\s+", " ", safe_line).strip()
        if safe_line:
            lines.append(safe_line)
    cleaned = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return cleaned[:limit]
