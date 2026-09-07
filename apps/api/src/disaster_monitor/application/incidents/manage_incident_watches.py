"""Create and manage local incident watches through canonical domain state."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.ports.incident_watch_store import IncidentWatchStore
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchScope,
    WatchScopeKind,
)


class InvalidIncidentWatchScopeError(ValueError):
    pass


class IncidentWatchNotFoundError(LookupError):
    pass


class ManageIncidentWatches:
    def __init__(
        self,
        store: IncidentWatchStore,
        country_catalog: CountryCatalog,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        identifier: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._store = store
        self._country_catalog = country_catalog
        self._clock = clock
        self._identifier = identifier

    async def create(
        self,
        *,
        disaster: Disaster,
        scope_kind: WatchScopeKind,
        country: str | None,
        refresh_interval_seconds: int,
    ) -> IncidentWatch:
        scope = self._canonical_scope(scope_kind, country)
        now = self._clock()
        created = IncidentWatch(
            watch_id=f"incident-watch:{self._identifier()}",
            disaster=disaster,
            scope=scope,
            enabled=True,
            refresh_interval_seconds=refresh_interval_seconds,
            created_at=now,
            updated_at=now,
            next_refresh_at=now,
        )
        if not await self._store.create_watch(created):
            raise RuntimeError("Incident watch identifier collision.")
        return created

    async def list(self) -> tuple[IncidentWatch, ...]:
        return await self._store.list_watches()

    async def set_enabled(self, watch_id: str, *, enabled: bool) -> IncidentWatch:
        updated = await self._store.set_watch_enabled(
            watch_id,
            enabled=enabled,
            updated_at=self._clock(),
        )
        if updated is None:
            raise IncidentWatchNotFoundError(watch_id)
        return updated

    async def delete(self, watch_id: str) -> None:
        if not await self._store.delete_watch(watch_id):
            raise IncidentWatchNotFoundError(watch_id)

    async def timeline(
        self, watch_id: str, *, limit: int = 100
    ) -> tuple[IncidentWatchChange, ...]:
        if await self._store.get_watch(watch_id) is None:
            raise IncidentWatchNotFoundError(watch_id)
        return await self._store.watch_changes(watch_id, limit=limit)

    async def mark_read(
        self, watch_id: str, change_ids: tuple[str, ...]
    ) -> tuple[int, IncidentWatch]:
        existing = await self._store.get_watch(watch_id)
        if existing is None:
            raise IncidentWatchNotFoundError(watch_id)
        marked = await self._store.mark_watch_changes_read(
            watch_id,
            tuple(dict.fromkeys(change_ids)),
            read_at=self._clock(),
        )
        updated = await self._store.get_watch(watch_id)
        if updated is None:
            raise IncidentWatchNotFoundError(watch_id)
        return marked, updated

    def _canonical_scope(
        self, scope_kind: WatchScopeKind, country_value: str | None
    ) -> IncidentWatchScope:
        if scope_kind is WatchScopeKind.WORLDWIDE:
            if country_value is not None and country_value.strip():
                raise InvalidIncidentWatchScopeError(
                    "Worldwide watch scope cannot include a country."
                )
            return IncidentWatchScope.worldwide()
        if country_value is None or not country_value.strip():
            raise InvalidIncidentWatchScopeError(
                "Country watch scope requires one supported country."
            )
        value = country_value.strip()
        matches = self._country_catalog.find_mentions(value)
        exact = tuple(item for item in matches if _is_exact_country_term(item, value))
        if len(exact) != 1:
            raise InvalidIncidentWatchScopeError(
                "Country watch scope must resolve to exactly one canonical country."
            )
        selected = exact[0]
        return IncidentWatchScope.country(selected.alpha3_code, selected.canonical_name)


def _is_exact_country_term(country: Country, value: str) -> bool:
    if value == country.alpha3_code:
        return True
    return value.casefold() in {
        country.canonical_name.casefold(),
        *(item.casefold() for item in country.aliases),
    }
