from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.imagery.regions import Coordinate
from disaster_monitor.domain.spatial_watches import (
    AreaOfInterestScope,
    LocalAsset,
    LocalAssetKind,
)
from disaster_monitor.infrastructure.operations.local_spatial_watch_store import (
    LocalSpatialWatchStore,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)


@pytest.mark.asyncio
async def test_local_spatial_watch_store_round_trips_versioned_private_geometries(
    tmp_path,
) -> None:
    path = tmp_path / "spatial-watches.json"
    first = LocalSpatialWatchStore(path)
    scope = AreaOfInterestScope.bounding_box(
        scope_id="aoi:home",
        name="Home area",
        min_latitude=10,
        min_longitude=106,
        max_latitude=11,
        max_longitude=107,
        version="operator-edit:1",
        updated_at=NOW,
    )
    asset = LocalAsset(
        asset_id="asset:home",
        name="Home",
        kind=LocalAssetKind.HOME,
        version="operator-edit:2",
        coordinate=Coordinate(10.5, 106.5),
        updated_at=NOW,
    )

    await first.save_scope(scope)
    await first.save_asset(asset)
    reopened = LocalSpatialWatchStore(path)

    assert await reopened.list_scopes() == (scope,)
    assert await reopened.list_assets() == (asset,)
    assert "10.5" in path.read_text()
