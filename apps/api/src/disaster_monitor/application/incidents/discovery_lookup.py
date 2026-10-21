"""Resolve one discovery inspection reference without crossing retained scans."""

from uuid import UUID

from disaster_monitor.application.incidents.discovery_projection import (
    discovery_incident,
)
from disaster_monitor.application.incidents.mention_geography import (
    resolve_event_places,
)
from disaster_monitor.application.incidents.models import ActiveIncident
from disaster_monitor.application.ports.discovery import DiscoveryStore
from disaster_monitor.application.ports.mention_geography import MentionPlaceResolver


class DiscoveryIncidentLookup:
    def __init__(
        self, store: DiscoveryStore, resolver: MentionPlaceResolver | None
    ) -> None:
        self._store = store
        self._resolver = resolver

    async def execute(self, identifier: str) -> ActiveIncident:
        parts = identifier.split(":", 2)
        if len(parts) == 3:
            try:
                scan_id = str(UUID(parts[1]))
            except ValueError:
                raise LookupError("Invalid retained discovery reference.") from None
            run = await self._store.read(scan_id)
            matches = (
                tuple(
                    (run, event) for event in run.events if event.event_id == parts[2]
                )
                if run
                else ()
            )
        else:
            # Migration for links saved before scan-qualified references. A naked
            # ordinal identifier must never silently choose another assessment.
            # Remove this path once those saved links are no longer supported.
            matches = tuple(
                (run, event)
                for run in await self._store.recent()
                for event in run.events
                if event.event_id == identifier
            )
        if len(matches) > 1:
            raise ValueError(
                "The discovery identifier is ambiguous across retained scans. "
                "Open the event from its saved scan to select its evidence."
            )
        if not matches:
            raise LookupError("Discovered event is no longer retained. Run a new scan.")
        run, event = matches[0]
        if event.geometry is None and event.event_time is not None and self._resolver:
            (event,) = await resolve_event_places((event,), self._resolver, maximum=2)
        return discovery_incident(
            event, run.finished_at or run.interval.end, scan_id=run.scan_id
        )
