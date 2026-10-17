"""Preserve unique provider aliases without changing physical reconciliation."""

import asyncio
import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta

from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsSnapshot,
)
from disaster_monitor.application.incidents.projection_codec import (
    projection_to_snapshot,
    snapshot_to_projection,
)
from disaster_monitor.application.ports.incident_identity_store import (
    IncidentIdentityStore,
)
from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionRecord,
)
from disaster_monitor.domain.event_identifiers import (
    EventIdentifierRole,
    event_identifier_role,
)


def _aliases(incident: ActiveIncident) -> set[str]:
    return {
        value
        for value in (
            incident.event_id,
            incident.physical_event_id,
            *incident.provider_ids,
        )
        if value and event_identifier_role(value) is EventIdentifierRole.PHYSICAL_EVENT
    }


class IncidentIdentityAssignments:
    def __init__(self, store: IncidentIdentityStore, *, maximum_records: int = 2000):
        self._store, self._maximum_records = store, maximum_records
        self._incidents: dict[str, ActiveIncident] = {}
        self._aliases: dict[str, set[str]] = {}
        self._seen: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        raw = store.read()
        if raw is not None:
            document = json.loads(raw)
            if document.get("version") != 1:
                raise ValueError("Unsupported incident identity store version.")
            when = datetime.fromisoformat(document["retrieved_at"])
            projection = IncidentProjectionRecord(
                "identities", "identities", when, when, document["projection"]
            )
            snapshot = projection_to_snapshot(projection)
            self._incidents = {
                item.physical_event_id or item.event_id: item
                for item in snapshot.incidents
            }
            self._aliases = {
                key: set(values) for key, values in document["aliases"].items()
            }
            self._seen = {
                key: datetime.fromisoformat(value)
                for key, value in document["seen"].items()
            }
            if len(self._incidents) > maximum_records:
                raise ValueError("Incident identity store exceeds its record bound.")

    async def stabilize(
        self, snapshot: ActiveIncidentsSnapshot
    ) -> ActiveIncidentsSnapshot:
        async with self._lock:
            now = snapshot.retrieved_at
            proposed = []
            for incident in snapshot.incidents:
                known = {
                    identity
                    for alias in _aliases(incident)
                    for identity in self._aliases.get(alias, ())
                    if identity in self._incidents
                    and now - self._seen[identity] <= timedelta(days=30)
                }
                proposed.append(next(iter(known)) if len(known) == 1 else None)
            counts = Counter(value for value in proposed if value)
            rows = []
            for incident, identity in zip(snapshot.incidents, proposed, strict=True):
                if identity and counts[identity] == 1:
                    incident = replace(incident, physical_event_id=identity)
                stable = incident.physical_event_id or incident.event_id
                self._incidents[stable] = incident
                self._seen[stable] = now
                for alias in _aliases(incident):
                    self._aliases.setdefault(alias, set()).add(stable)
                rows.append(incident)
            # A formerly merged cluster can split. Its old link must disclose ambiguity.
            for previous, count in counts.items():
                if count <= 1:
                    continue
                replacements = {
                    row.physical_event_id or row.event_id
                    for row, proposed_id in zip(rows, proposed, strict=True)
                    if proposed_id == previous
                }
                current_aliases: dict[str, set[str]] = {}
                for row in rows:
                    for alias in _aliases(row):
                        current_aliases.setdefault(alias, set()).add(
                            row.physical_event_id or row.event_id
                        )
                for alias, identities in tuple(self._aliases.items()):
                    if previous in identities:
                        self._aliases[alias] = current_aliases.get(
                            alias, (identities - {previous}) | replacements
                        )
                self._aliases[previous] = replacements
                self._incidents.pop(previous, None)
                self._seen.pop(previous, None)
            sorted_keys = sorted(
                self._seen, key=lambda key: (self._seen[key], key), reverse=True
            )
            retained = {
                key
                for key in sorted_keys[: self._maximum_records]
                if now - self._seen[key] <= timedelta(days=30)
            }
            self._incidents = {
                key: value for key, value in self._incidents.items() if key in retained
            }
            self._seen = {
                key: value for key, value in self._seen.items() if key in retained
            }
            self._aliases = {
                key: values & retained
                for key, values in self._aliases.items()
                if values & retained
            }
            # Aliases are additionally bounded; physical IDs and newest records win.
            if len(self._aliases) > self._maximum_records * 16:
                self._aliases = dict(
                    list(self._aliases.items())[-self._maximum_records * 16 :]
                )
            archive = replace(
                snapshot,
                incidents=tuple(self._incidents.values()),
                observations=(),
                coverage=(),
                warnings=(),
                correlations=(),
                snapshot_version="identities",
            )
            projection = snapshot_to_projection(archive, created_at=now)
            await self._store.write(
                json.dumps(
                    {
                        "version": 1,
                        "retrieved_at": now.isoformat(),
                        "projection": projection.payload_json,
                        "aliases": {
                            key: sorted(values) for key, values in self._aliases.items()
                        },
                        "seen": {
                            key: value.isoformat() for key, value in self._seen.items()
                        },
                    },
                    separators=(",", ":"),
                )
            )
            return replace(snapshot, incidents=tuple(rows))

    def lookup(self, identifier: str, *, now: datetime) -> ActiveIncident | None:
        matches = [
            self._incidents[identity]
            for identity in self._aliases.get(identifier, ())
            if identity in self._incidents
            and now - self._seen[identity] <= timedelta(days=30)
        ]
        if len(matches) > 1:
            raise ValueError(
                "The retained incident identifier is ambiguous. Select a "
                "current physical event."
            )
        return matches[0] if matches else None
