from __future__ import annotations

import asyncio
import io
import json
import tarfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from disaster_monitor.application.ports.geography import (
    CountryCatalogUpdateState,
    CountryCatalogUpdateStatus,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.infrastructure.geography.country_catalog_updates import (
    AutonomousCountryCatalogUpdater,
    CountryCatalogAutomation,
    CountryCatalogSourceSnapshot,
    VersionedCountryCatalogStore,
    build_country_catalog_payload,
    next_country_catalog_update_at,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 15, 8, tzinfo=UTC)


class FakeSource:
    def __init__(self, snapshot: CountryCatalogSourceSnapshot) -> None:
        self.snapshot = snapshot
        self.closed = False

    async def fetch(self) -> CountryCatalogSourceSnapshot:
        return self.snapshot

    async def aclose(self) -> None:
        self.closed = True


class FakeUpdater:
    def __init__(self) -> None:
        self.calls: list[CountryCatalogUpdateTrigger] = []
        self.current = CountryCatalogUpdateStatus(
            CountryCatalogUpdateState.NEVER_RUN,
            "1.0.0",
            3,
            True,
        )

    def status(self) -> CountryCatalogUpdateStatus:
        return self.current

    async def update(
        self, trigger: CountryCatalogUpdateTrigger
    ) -> CountryCatalogUpdateStatus:
        self.calls.append(trigger)
        self.current = CountryCatalogUpdateStatus(
            CountryCatalogUpdateState.UPDATED,
            "2.0.0",
            242,
            True,
            trigger=trigger,
            last_attempt_at=NOW,
            last_success_at=NOW,
        )
        return self.current

    async def aclose(self) -> None:
        return None


def _feature(alpha3: str, alpha2: str, name: str, offset: int) -> dict[str, object]:
    longitude = float(offset * 2)
    return {
        "type": "Feature",
        "properties": {
            "ISO_A3_EH": alpha3,
            "ISO_A3": alpha3,
            "ADM0_A3": alpha3,
            "ISO_A2_EH": alpha2,
            "NAME_LONG": name,
            "ADMIN": name,
            "NAME_ES": f"{name} ES",
            "LABEL_X": longitude + 0.5,
            "LABEL_Y": 0.5,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [longitude, 0.0],
                    [longitude + 1.0, 0.0],
                    [longitude + 1.0, 1.0],
                    [longitude, 1.0],
                    [longitude, 0.0],
                ]
            ],
        },
    }


def _tzdata() -> bytes:
    codes = [
        f"{first}{second}"
        for first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for second in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ]
    required = {"FR", "JP", "TR", "US", "VE", "VN"}
    selected = sorted(required | set(codes[:200]))
    zone_lines = [f"{code}\t+0000+00000\tEtc/{code}" for code in selected]
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in (
            ("version", b"2026b\n"),
            ("zone.tab", ("\n".join(zone_lines) + "\n").encode()),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def _snapshot() -> CountryCatalogSourceSnapshot:
    countries = (
        ("FRA", "FR", "France"),
        ("JPN", "JP", "Japan"),
        ("TUR", "TR", "Türkiye"),
        ("USA", "US", "United States"),
        ("VEN", "VE", "Venezuela"),
        ("VNM", "VN", "Vietnam"),
    )
    geography = {
        "type": "FeatureCollection",
        "features": [
            _feature(alpha3, alpha2, name, index)
            for index, (alpha3, alpha2, name) in enumerate(countries)
        ],
    }
    return CountryCatalogSourceSnapshot(
        natural_earth_version="v5.1.2",
        natural_earth_revision="a" * 40,
        natural_earth_published_at="2026-05-13T23:24:00Z",
        natural_earth_url=(
            "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
            f"{'a' * 40}/geojson/ne_50m_admin_0_countries.geojson"
        ),
        natural_earth_bytes=json.dumps(geography).encode(),
        tzdata_url="https://data.iana.org/time-zones/tzdata-latest.tar.gz",
        tzdata_bytes=_tzdata(),
    )


def test_generator_builds_deterministic_global_metadata() -> None:
    snapshot = _snapshot()

    first = build_country_catalog_payload(snapshot, minimum_country_count=6)
    second = build_country_catalog_payload(snapshot, minimum_country_count=6)

    assert first == second
    assert first["metadata"]["country_count"] == 6  # type: ignore[index]
    countries = {item["alpha3"]: item for item in first["countries"]}  # type: ignore[index]
    assert countries["JPN"]["timezone"] == "Etc/JP"
    assert countries["USA"]["timezone"] == "Etc/US"
    assert "United States ES" in countries["USA"]["aliases"]
    assert countries["JPN"]["polygons"]


def test_generator_keeps_dependencies_distinct_from_shared_iso_view() -> None:
    snapshot = _snapshot()
    geography = json.loads(snapshot.natural_earth_bytes)
    geography["features"].append(_feature("AUS", "AU", "Australia", 10))
    dependency = _feature("AUS", "AU", "Indian Ocean Territories", 11)
    dependency["properties"]["ISO_A3"] = "-99"  # type: ignore[index]
    dependency["properties"]["ADM0_A3"] = "IOA"  # type: ignore[index]
    geography["features"].append(dependency)

    payload = build_country_catalog_payload(
        replace(snapshot, natural_earth_bytes=json.dumps(geography).encode()),
        minimum_country_count=6,
    )

    codes = {item["alpha3"] for item in payload["countries"]}  # type: ignore[index]
    assert {"AUS", "IOA"}.issubset(codes)


@pytest.mark.asyncio
async def test_update_promotes_once_and_retains_last_good_on_failure(
    tmp_path: Path,
) -> None:
    catalog = StaticCountryCatalog(tmp_path)
    source = FakeSource(_snapshot())
    updater = AutonomousCountryCatalogUpdater(
        catalog=catalog,
        store=VersionedCountryCatalogStore(tmp_path, catalog),
        source=source,
        automatic_updates_enabled=True,
        clock=lambda: NOW,
        minimum_country_count=6,
    )

    promoted = await updater.update(CountryCatalogUpdateTrigger.SCRIPT)
    unchanged = await updater.update(CountryCatalogUpdateTrigger.MANUAL)
    source.snapshot = replace(source.snapshot, natural_earth_bytes=b"{}")
    failed = await updater.update(CountryCatalogUpdateTrigger.SCHEDULED)

    assert promoted.state == CountryCatalogUpdateState.UPDATED
    assert unchanged.state == CountryCatalogUpdateState.UNCHANGED
    assert failed.state == CountryCatalogUpdateState.FAILED
    assert failed.active_version == promoted.active_version
    assert catalog.get_by_alpha3("USA") is not None
    assert len(catalog.countries()) == 6
    assert (tmp_path / "active.json").is_file()


def test_monthly_schedule_catches_up_and_retries_failures() -> None:
    base = CountryCatalogUpdateStatus(
        CountryCatalogUpdateState.NEVER_RUN,
        "1.0.0",
        3,
        True,
    )
    assert next_country_catalog_update_at(
        base, now=NOW, retry_interval=timedelta(hours=6)
    ) == datetime(2026, 8, 1, tzinfo=UTC)

    failed = CountryCatalogUpdateStatus(
        CountryCatalogUpdateState.FAILED,
        "1.0.0",
        3,
        True,
        last_attempt_at=NOW,
    )
    assert next_country_catalog_update_at(
        failed, now=NOW, retry_interval=timedelta(hours=6)
    ) == NOW + timedelta(hours=6)

    succeeded = CountryCatalogUpdateStatus(
        CountryCatalogUpdateState.UPDATED,
        "2.0.0",
        242,
        True,
        last_success_at=NOW,
    )
    assert next_country_catalog_update_at(
        succeeded, now=NOW, retry_interval=timedelta(hours=6)
    ) == datetime(2026, 9, 1, tzinfo=UTC)


def test_invalid_active_catalog_falls_back_to_packaged_metadata(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "active.json").write_text(
        '{"metadata":{"version":"broken"},"countries":[]}', encoding="utf-8"
    )

    catalog = StaticCountryCatalog(tmp_path)

    assert catalog.metadata["version"] == "1.0.0"
    assert [country.alpha3_code for country in catalog.countries()] == [
        "JPN",
        "VNM",
        "VEN",
    ]


@pytest.mark.asyncio
async def test_automation_runs_a_due_monthly_update_without_intervention() -> None:
    updater = FakeUpdater()
    automation = CountryCatalogAutomation(  # type: ignore[arg-type]
        updater,
        automatic_updates_enabled=True,
        retry_interval=timedelta(hours=6),
        clock=lambda: NOW,
    )

    await automation.start()
    for _ in range(20):
        if updater.calls:
            break
        await asyncio.sleep(0)
    await automation.aclose()

    assert updater.calls == [CountryCatalogUpdateTrigger.SCHEDULED]
