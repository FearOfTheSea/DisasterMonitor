"""Bound attributed disaster accounts inside potentially multi-topic reporting.

This is a conservative English heuristic, not semantic causal verification. Original
report text and links remain retained even when an account cannot be safely scoped.
"""

import re

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.hazards.news_classification import disasters_in_text

_OTHER_CAUSE = re.compile(
    r"\b(?:conflict|violence|cholera|ebola|measles|covid-?19|war|warfare|"
    r"airstrikes?|bombing|gunfire|shootings?|armed attacks?)\b",
    re.I,
)


def scoped_disaster_text(text: str, title: str, disaster: Disaster | None) -> str:
    """Never assign competing causes or another hazard's figures to this event.

    An unambiguous hazard headline can supply context for otherwise unqualified
    sentences. Broad/multi-topic headlines require the hazard in the same sentence.
    Mixed-cause sentences remain in the source, rather than becoming hazard totals.
    """
    if disaster is None:
        return ""
    headline_context = disasters_in_text(title) == (disaster,)
    retained = []
    for sentence in re.split(r"(?<=[.!?])\s+", text[:20_000]):
        if _OTHER_CAUSE.search(sentence):
            continue
        hazards = disasters_in_text(sentence)
        if hazards == (disaster,) or (not hazards and headline_context):
            retained.append(sentence)
    return " ".join(retained)
