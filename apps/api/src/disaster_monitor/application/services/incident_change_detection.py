"""Deterministic typed-state comparison for incident watch refreshes."""

from disaster_monitor.domain.disaster import (
    IncidentChangeKind,
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchObservation,
    WatchIncident,
)


class IncidentChangeDetector:
    """Classify meaningful changes without rendered text or model output."""

    def detect(
        self,
        *,
        watch: IncidentWatch,
        previous: IncidentWatchObservation | None,
        previous_successful: IncidentWatchObservation | None,
        current: IncidentWatchObservation,
    ) -> tuple[IncidentWatchChange, ...]:
        changes: list[IncidentWatchChange] = []
        if previous is not None and previous.coverage_state != current.coverage_state:
            changes.append(
                IncidentWatchChange.create_coverage_change(
                    watch=watch, previous=previous, current=current
                )
            )
        if not current.successful:
            return tuple(changes)

        old_by_id = {
            item.physical_event_id: item
            for item in (
                previous_successful.incidents if previous_successful is not None else ()
            )
        }
        new_by_id = {item.physical_event_id: item for item in current.incidents}
        matched = _matched_incidents(old_by_id, new_by_id)
        matched_old_ids = {old_id for old_id, _ in matched}
        matched_new_ids = {new_id for _, new_id in matched}

        for new_id in sorted(set(new_by_id) - matched_new_ids):
            current_incident = new_by_id[new_id]
            changes.append(
                _event_change(
                    watch,
                    IncidentChangeKind.NEW_EVENT,
                    current,
                    previous,
                    current_incident,
                    "New physical event discovered",
                    (
                        "A new source-backed physical event appeared in the bounded "
                        "provider result."
                    ),
                    None,
                    current_incident.state_hash,
                )
            )
        for old_id in sorted(set(old_by_id) - matched_old_ids):
            prior_incident = old_by_id[old_id]
            changes.append(
                _event_change(
                    watch,
                    IncidentChangeKind.OBSERVATION_GAP,
                    current,
                    previous,
                    prior_incident,
                    "Previously observed event absent from bounded result",
                    (
                        "The previously observed event is no longer present in this "
                        "bounded provider result. This is an observation gap and is "
                        "not evidence that the disaster ended."
                    ),
                    prior_incident.state_hash,
                    None,
                )
            )
        for old_id, new_id in matched:
            prior_incident = old_by_id[old_id]
            current_incident = new_by_id[new_id]
            comparisons = (
                (
                    IncidentChangeKind.MEASUREMENTS_CHANGED,
                    prior_incident.measurements_hash,
                    current_incident.measurements_hash,
                    "Source-backed measurements changed",
                    "One or more typed source-backed event measurements changed.",
                ),
                (
                    IncidentChangeKind.GEOMETRY_CHANGED,
                    prior_incident.geometry_hash,
                    current_incident.geometry_hash,
                    "Source-backed geometry changed",
                    "The exact source-backed event geometry changed.",
                ),
                (
                    IncidentChangeKind.EVIDENCE_SET_CHANGED,
                    prior_incident.evidence_hash,
                    current_incident.evidence_hash,
                    "Event evidence set changed",
                    "The event's provider identifiers or source evidence set changed.",
                ),
            )
            for kind, before_hash, after_hash, summary, detail in comparisons:
                if before_hash == after_hash:
                    continue
                changes.append(
                    _event_change(
                        watch,
                        kind,
                        current,
                        previous,
                        current_incident,
                        summary,
                        detail,
                        before_hash,
                        after_hash,
                        extra_source_ids=prior_incident.source_ids,
                    )
                )
        return tuple(changes)


def _matched_incidents(
    old_by_id: dict[str, WatchIncident],
    new_by_id: dict[str, WatchIncident],
) -> tuple[tuple[str, str], ...]:
    matches = [
        (event_id, event_id) for event_id in sorted(old_by_id.keys() & new_by_id)
    ]
    remaining_old = sorted(set(old_by_id) - {item[0] for item in matches})
    remaining_new = sorted(set(new_by_id) - {item[1] for item in matches})
    for old_id in remaining_old:
        old_identifiers = set(old_by_id[old_id].provider_ids)
        candidates = [
            new_id
            for new_id in remaining_new
            if old_identifiers & set(new_by_id[new_id].provider_ids)
        ]
        if len(candidates) != 1:
            continue
        new_id = candidates[0]
        matches.append((old_id, new_id))
        remaining_new.remove(new_id)
    return tuple(sorted(matches))


def _event_change(
    watch: IncidentWatch,
    kind: IncidentChangeKind,
    current: IncidentWatchObservation,
    previous: IncidentWatchObservation | None,
    incident: WatchIncident,
    summary: str,
    detail: str,
    before_hash: str | None,
    after_hash: str | None,
    *,
    extra_source_ids: tuple[str, ...] = (),
) -> IncidentWatchChange:
    return IncidentWatchChange.create(
        watch=watch,
        kind=kind,
        current=current,
        previous=previous,
        summary=summary,
        detail=detail,
        incident=incident,
        before_hash=before_hash,
        after_hash=after_hash,
        source_ids=(*incident.source_ids, *extra_source_ids),
    )
