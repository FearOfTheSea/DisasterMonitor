"""Deterministic, bounded context derived from one persisted conversation."""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.conversation import (
    ConversationMessage,
    ConversationRole,
)
from disaster_monitor.domain.disaster import Country, Disaster

MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_CHARACTERS = 6_000

_REFERENTIAL_TERMS = re.compile(
    r"(?:\bwhat\s+about\b|\bhow\s+about\b|\bthere\b|\bhere\b|"
    r"\b(?:that|this|it|same)\b|^and\b|\bmore\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _DisasterAnchor:
    disaster: Disaster
    country: Country


def select_bounded_history(
    messages: Iterable[ConversationMessage],
    *,
    conversation_id: str | None = None,
    max_messages: int = MAX_HISTORY_MESSAGES,
    max_characters: int = MAX_HISTORY_CHARACTERS,
) -> tuple[ConversationMessage, ...]:
    """Select newest whole messages while retaining a valid turn boundary."""
    if max_messages < 0 or max_characters < 0:
        raise ValueError("History bounds must not be negative.")

    candidates = sorted(
        (
            message
            for message in messages
            if conversation_id is None or message.conversation_id == conversation_id
        ),
        key=lambda message: (message.created_at, message.message_id),
    )
    selected_reversed: list[ConversationMessage] = []
    character_count = 0
    for message in reversed(candidates):
        if len(selected_reversed) >= max_messages:
            break
        message_length = len(message.content)
        if message_length > max_characters:
            continue
        if character_count + message_length > max_characters:
            continue
        selected_reversed.append(message)
        character_count += message_length

    selected = list(reversed(selected_reversed))
    while selected and selected[0].role is ConversationRole.ASSISTANT:
        selected.pop(0)
    return tuple(selected)


def resolve_disaster_follow_up(
    question: str,
    history: Iterable[ConversationMessage],
    *,
    country_catalog: CountryCatalog | None,
    conversation_id: str | None = None,
) -> str:
    """Resolve only clearly referential disaster follow-ups from user turns."""
    from disaster_monitor.application.agent.task_normalization import (
        disaster_safety_gate,
    )
    from disaster_monitor.application.services.prompt_preparation import (
        normalize_question,
    )

    normalized = normalize_question(question)
    if country_catalog is None or not _REFERENTIAL_TERMS.search(normalized):
        return normalized

    current_disasters = _recognized_disasters(normalized)
    current_countries = country_catalog.find_mentions(normalized)
    if len(current_disasters) > 1 or len(current_countries) > 1:
        return normalized

    anchor = _most_recent_safe_anchor(
        history,
        country_catalog=country_catalog,
        conversation_id=conversation_id,
        disaster_safety_gate=disaster_safety_gate,
    )
    if anchor is None:
        return normalized

    disaster = current_disasters[0] if current_disasters else anchor.disaster
    country = current_countries[0] if current_countries else anchor.country
    if current_disasters and current_countries:
        return normalized

    resolved = (
        f"What are the latest {_plural_disaster_name(disaster)} "
        f"in {country.canonical_name}?"
    )
    if normalized.casefold() not in {
        f"what about {country.canonical_name.casefold()}?",
        f"how about {country.canonical_name.casefold()}?",
    }:
        resolved = f"{resolved} {normalized}"
    return resolved


def _most_recent_safe_anchor(
    history: Iterable[ConversationMessage],
    *,
    country_catalog: CountryCatalog,
    conversation_id: str | None,
    disaster_safety_gate: Callable[[str], bool],
) -> _DisasterAnchor | None:
    candidates = sorted(
        (
            message
            for message in history
            if message.role is ConversationRole.USER
            and (conversation_id is None or message.conversation_id == conversation_id)
        ),
        key=lambda message: (message.created_at, message.message_id),
        reverse=True,
    )
    for message in candidates:
        disasters = _recognized_disasters(message.content)
        countries = country_catalog.find_mentions(message.content)
        if (
            len(disasters) == 1
            and len(countries) == 1
            and disaster_safety_gate(message.content)
        ):
            return _DisasterAnchor(disasters[0], countries[0])
    return None


def _recognized_disasters(text: str) -> tuple[Disaster, ...]:
    from disaster_monitor.application.disaster_aliases import recognized_disasters

    return recognized_disasters(text)


def _plural_disaster_name(disaster: Disaster) -> str:
    name = disaster.value.replace("_", " ")
    if name.endswith("y"):
        return f"{name[:-1]}ies"
    if name.endswith("s"):
        return name
    return f"{name}s"
