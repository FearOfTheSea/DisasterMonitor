"""Autonomous, fail-closed generation and promotion of global country metadata."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from disaster_monitor.application.ports.geography import (
    CountryCatalogSourceVersion,
    CountryCatalogUpdateState,
    CountryCatalogUpdateStatus,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
    parse_country_catalog_payload,
)

_SAFE_VERSION = re.compile(r"[A-Za-z0-9._-]{1,160}")


class VersionedCountryCatalogStore:
    """Persist immutable candidates and atomically switch the active catalog."""

    def __init__(self, root: Path, catalog: StaticCountryCatalog) -> None:
        self.root = root
        self.active_path = root / "active.json"
        self.status_path = root / "update-status.json"
        self.lock_path = root / "update.lock"
        self._archives = root / "catalogs"
        self._catalog = catalog

    def promote(self, payload: Mapping[str, object], serialized: bytes) -> None:
        metadata, _ = parse_country_catalog_payload(payload)
        version = str(metadata.get("version", ""))
        if not _SAFE_VERSION.fullmatch(version):
            raise ValueError("Generated country catalog version is invalid.")
        self._archives.mkdir(parents=True, exist_ok=True)
        archive = self._archives / f"countries.{version}.json"
        if archive.exists():
            if archive.read_bytes() != serialized:
                raise ValueError(
                    "An immutable country catalog version changed content."
                )
        else:
            _atomic_write(archive, serialized)
        previous = self.active_path.read_bytes() if self.active_path.exists() else None
        _atomic_write(self.active_path, serialized)
        try:
            self._catalog.activate_payload(payload)
            self._catalog.mark_active_path_current()
        except Exception:
            if previous is None:
                self.active_path.unlink(missing_ok=True)
            else:
                _atomic_write(self.active_path, previous)
                restored = cast(dict[str, object], json.loads(previous.decode("utf-8")))
                self._catalog.activate_payload(restored)
                self._catalog.mark_active_path_current()
            raise

    def read_status(self) -> Mapping[str, Any] | None:
        if not self.status_path.is_file():
            return None
        try:
            return _json_object(self.status_path.read_bytes())
        except (OSError, ValueError, TypeError):
            return None

    def write_status(self, status: Mapping[str, object]) -> None:
        serialized = (
            json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n"
        )
        _atomic_write(self.status_path, serialized)

    def acquire_lease(self, now: datetime) -> bool:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError:
            try:
                age = now.timestamp() - self.lock_path.stat().st_mtime
                if age <= 2 * 60 * 60:
                    return False
                self.lock_path.unlink()
            except OSError:
                return False
            return self.acquire_lease(now)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(now.astimezone(UTC).isoformat())
        return True

    def release_lease(self) -> None:
        self.lock_path.unlink(missing_ok=True)


def _serialize_status(status: CountryCatalogUpdateStatus) -> dict[str, object]:
    return {
        "state": status.state.value,
        "trigger": status.trigger.value if status.trigger else None,
        "active_version": status.active_version,
        "country_count": status.country_count,
        "last_attempt_at": _datetime_text(status.last_attempt_at),
        "last_success_at": _datetime_text(status.last_success_at),
        "message": status.message,
        "failure_code": status.failure_code,
        "sources": [
            {
                "source_id": source.source_id,
                "version": source.version,
                "revision": source.revision,
                "sha256": source.sha256,
            }
            for source in status.sources
        ],
    }


def _deserialize_status(
    payload: Mapping[str, Any] | None,
    *,
    catalog: StaticCountryCatalog,
    automatic_updates_enabled: bool,
) -> CountryCatalogUpdateStatus:
    metadata = catalog.metadata
    active_version = str(metadata.get("version", "unknown"))
    country_count = len(catalog.countries())
    if payload is None:
        return CountryCatalogUpdateStatus(
            CountryCatalogUpdateState.NEVER_RUN,
            active_version,
            country_count,
            automatic_updates_enabled,
        )
    try:
        state = CountryCatalogUpdateState(str(payload.get("state")))
        trigger_value = payload.get("trigger")
        trigger = (
            CountryCatalogUpdateTrigger(str(trigger_value))
            if trigger_value is not None
            else None
        )
        source_payloads = payload.get("sources", [])
        if not isinstance(source_payloads, list):
            raise ValueError("Invalid stored source status.")
        sources = tuple(
            CountryCatalogSourceVersion(
                _required_string(_json_object(item), "source_id"),
                _required_string(_json_object(item), "version"),
                _required_string(_json_object(item), "revision"),
                _required_string(_json_object(item), "sha256"),
            )
            for item in source_payloads
        )
        return CountryCatalogUpdateStatus(
            state=state,
            active_version=active_version,
            country_count=country_count,
            automatic_updates_enabled=automatic_updates_enabled,
            trigger=trigger,
            last_attempt_at=_parse_datetime(payload.get("last_attempt_at")),
            last_success_at=_parse_datetime(payload.get("last_success_at")),
            message=str(
                payload.get("message") or "Country catalog status is available."
            ),
            failure_code=(
                str(payload["failure_code"])
                if payload.get("failure_code") is not None
                else None
            ),
            sources=sources,
        )
    except (TypeError, ValueError, KeyError):
        return CountryCatalogUpdateStatus(
            state=CountryCatalogUpdateState.FAILED,
            active_version=active_version,
            country_count=country_count,
            automatic_updates_enabled=automatic_updates_enabled,
            message=(
                "Stored update status was invalid; the active country catalog was "
                "retained."
            ),
            failure_code="invalid_status",
        )


def _replace_status(
    status: CountryCatalogUpdateStatus, **changes: object
) -> CountryCatalogUpdateStatus:
    values: dict[str, object] = {
        "state": status.state,
        "active_version": status.active_version,
        "country_count": status.country_count,
        "automatic_updates_enabled": status.automatic_updates_enabled,
        "trigger": status.trigger,
        "last_attempt_at": status.last_attempt_at,
        "last_success_at": status.last_success_at,
        "next_scheduled_at": status.next_scheduled_at,
        "message": status.message,
        "failure_code": status.failure_code,
        "sources": status.sources,
    }
    values.update(changes)
    return CountryCatalogUpdateStatus(**cast(Any, values))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_object(value: object) -> Mapping[str, Any]:
    if isinstance(value, bytes):
        try:
            value = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Country catalog source returned invalid JSON.") from error
    if not isinstance(value, Mapping):
        raise ValueError("Country catalog source JSON must be an object.")
    return cast(Mapping[str, Any], value)


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"Country catalog source is missing {key}.")
    return item.strip()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Country catalog automation requires timezone-aware time.")
    return value.astimezone(UTC)


def _datetime_text(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Stored catalog update time is invalid.")
    parsed = datetime.fromisoformat(value)
    return _aware_utc(parsed)
