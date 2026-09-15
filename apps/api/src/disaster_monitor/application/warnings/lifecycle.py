"""Deterministic CAP update, cancellation, duplicate, and expiry reconciliation."""

from dataclasses import replace
from datetime import datetime

from disaster_monitor.domain.warnings import (
    CapAlert,
    CapMessageType,
    ReconciledWarning,
    WarningLifecycleState,
)


def reconcile_cap_messages(
    messages: tuple[CapAlert, ...], *, now: datetime
) -> tuple[ReconciledWarning, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("CAP lifecycle evaluation time must be timezone-aware.")
    unique: dict[tuple[str, str, datetime], CapAlert] = {}
    for message in sorted(messages, key=lambda item: (item.sent, item.identifier)):
        existing = unique.get(message.message_key)
        if existing is None:
            unique[message.message_key] = message
        else:
            infos = tuple(dict.fromkeys((*existing.infos, *message.infos)))
            unique[message.message_key] = replace(existing, infos=infos)

    referenced = {
        reference.key
        for message in unique.values()
        for reference in message.references
        if reference.key in unique
    }
    leaves = [message for key, message in unique.items() if key not in referenced]
    results = [
        ReconciledWarning(
            alert=message,
            state=_state(message, now),
            superseded_identifiers=_ancestor_identifiers(message, unique),
        )
        for message in leaves
    ]
    return tuple(
        sorted(
            results,
            key=lambda item: (item.alert.sent, item.alert.identifier),
            reverse=True,
        )
    )


def _state(message: CapAlert, now: datetime) -> WarningLifecycleState:
    if message.message_type is CapMessageType.CANCEL:
        return WarningLifecycleState.CANCELLED
    expiries = tuple(info.expires for info in message.infos if info.expires is not None)
    if expiries and max(expiries) <= now:
        return WarningLifecycleState.EXPIRED
    return WarningLifecycleState.ACTIVE


def _ancestor_identifiers(
    message: CapAlert,
    messages: dict[tuple[str, str, datetime], CapAlert],
) -> tuple[str, ...]:
    found: set[str] = set()
    pending = list(message.references)
    while pending:
        reference = pending.pop()
        previous = messages.get(reference.key)
        if previous is None or previous.identifier in found:
            continue
        found.add(previous.identifier)
        pending.extend(previous.references)
    return tuple(sorted(found))
