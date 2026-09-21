import asyncio
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.ground_imagery.catalog_search import (
    GroundImageryCatalogSearcher,
)
from disaster_monitor.application.ground_imagery.temporal_policy import (
    build_temporal_plan,
)
from disaster_monitor.application.ports.ground_imagery.catalog import (
    CatalogSearchError,
    GroundImageryCatalogPage,
    GroundImageryCatalogQuery,
)
from disaster_monitor.domain.disaster import Disaster, IncidentActivityStatus
from disaster_monitor.domain.imagery.observations import Sensor
from disaster_monitor.domain.imagery.regions import polygon_from_geojson


class SensorBarrierCatalog:
    def __init__(self) -> None:
        self.started_sensors: set[Sensor] = set()
        self._both_sensors_started = asyncio.Event()

    async def search(
        self, query: GroundImageryCatalogQuery
    ) -> GroundImageryCatalogPage:
        if query.sensor not in self.started_sensors:
            self.started_sensors.add(query.sensor)
            if len(self.started_sensors) == 2:
                self._both_sensors_started.set()
            await self._both_sensors_started.wait()
        return GroundImageryCatalogPage((), None, 0, True)

    async def aclose(self) -> None:
        return None


class FailingCatalog:
    def __init__(self) -> None:
        self.queries: list[GroundImageryCatalogQuery] = []

    async def search(
        self, query: GroundImageryCatalogQuery
    ) -> GroundImageryCatalogPage:
        self.queries.append(query)
        raise CatalogSearchError(
            "The catalog timed out.",
            reason_code="catalog_timeout",
            retryable=True,
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_independent_sensor_searches_start_concurrently() -> None:
    catalog = SensorBarrierCatalog()
    searcher = GroundImageryCatalogSearcher(catalog, maximum_catalog_items=20)
    geometry = polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
        }
    )
    plan = build_temporal_plan(
        onset=None,
        reference_time=datetime(2026, 9, 21, tzinfo=UTC),
        disaster=Disaster.FLOOD,
        activity_status=IncidentActivityStatus.ONGOING,
    )

    result = await asyncio.wait_for(
        searcher.search(geometry, plan, (Sensor.SENTINEL_1, Sensor.SENTINEL_2)),
        timeout=1,
    )

    assert catalog.started_sensors == {Sensor.SENTINEL_1, Sensor.SENTINEL_2}
    assert tuple(status.sensor for status in result.statuses) == (
        Sensor.SENTINEL_1,
        Sensor.SENTINEL_2,
    )


@pytest.mark.asyncio
async def test_sensor_search_stops_after_catalog_failure() -> None:
    catalog = FailingCatalog()
    searcher = GroundImageryCatalogSearcher(catalog, maximum_catalog_items=20)
    geometry = polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
        }
    )
    plan = build_temporal_plan(
        onset=None,
        reference_time=datetime(2026, 9, 21, tzinfo=UTC),
        disaster=Disaster.FLOOD,
        activity_status=IncidentActivityStatus.ONGOING,
    )

    result = await searcher.search(
        geometry, plan, (Sensor.SENTINEL_1, Sensor.SENTINEL_2)
    )

    assert [query.sensor for query in catalog.queries] == [
        Sensor.SENTINEL_1,
        Sensor.SENTINEL_2,
    ]
    assert [status.failure_code for status in result.statuses] == [
        "catalog_timeout",
        "catalog_timeout",
    ]
