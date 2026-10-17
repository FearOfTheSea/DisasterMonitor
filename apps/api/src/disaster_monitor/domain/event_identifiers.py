"""Identifier roles distinguish physical occurrences from shared context."""

from enum import StrEnum


class EventIdentifierRole(StrEnum):
    PHYSICAL_EVENT = "physical_event"
    CONTEXT = "context"


def event_identifier_role(identifier: str) -> EventIdentifierRole:
    """GLIDE and sequence references can cover several physical occurrences."""
    namespace = identifier.strip().casefold().split(":", 1)[0]
    if namespace in {"glide", "sequence", "earthquake-sequence", "parent"}:
        return EventIdentifierRole.CONTEXT
    return EventIdentifierRole.PHYSICAL_EVENT
