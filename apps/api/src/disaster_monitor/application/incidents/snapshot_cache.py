"""Time- and byte-bounded immutable incident snapshots."""

from collections import OrderedDict
from datetime import datetime, timedelta

from disaster_monitor.application.incidents.models import ActiveIncidentsSnapshot
from disaster_monitor.application.incidents.projection_codec import (
    snapshot_to_projection,
)


class IncidentCursorExpiredError(ValueError):
    pass


class IncidentSnapshotCache:
    def __init__(
        self,
        *,
        maximum_bytes: int = 64 * 1024**2,
        lifetime: timedelta = timedelta(minutes=30),
    ) -> None:
        self._lifetime = lifetime
        self._maximum_bytes = maximum_bytes
        self._entries: OrderedDict[
            str, tuple[ActiveIncidentsSnapshot, datetime, int]
        ] = OrderedDict()
        self._bytes = 0

    def put(self, snapshot: ActiveIncidentsSnapshot, *, now: datetime) -> None:
        version = snapshot.snapshot_version
        if version is None or version in self._entries:
            return
        self._expire(now)
        size = len(
            snapshot_to_projection(snapshot, created_at=now).payload_json.encode()
        )
        if size > self._maximum_bytes:
            return
        while self._entries and self._bytes + size > self._maximum_bytes:
            _, (_, _, removed) = self._entries.popitem(last=False)
            self._bytes -= removed
        self._entries[version] = (snapshot, now + self._lifetime, size)
        self._bytes += size

    def get(self, version: str, *, now: datetime) -> ActiveIncidentsSnapshot | None:
        self._expire(now)
        entry = self._entries.get(version)
        return entry[0] if entry else None

    def _expire(self, now: datetime) -> None:
        for version, (_, expires, size) in tuple(self._entries.items()):
            if expires <= now:
                del self._entries[version]
                self._bytes -= size
