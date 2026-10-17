"""Manual deployments never advertise scheduled work as executable."""

from pathlib import Path

import httpx
import pytest
from conftest import FakeLanguageModel

from disaster_monitor.infrastructure.composition import AppDependencyOverrides
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.main import create_app


@pytest.mark.asyncio
async def test_manual_runtime_blocks_watch_creation_but_preserves_reads(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(
            country_catalog_root=tmp_path / "countries",
            country_catalog_automatic_updates=False,
            field_media_root=tmp_path / "media",
            field_report_store_path=tmp_path / "reports.json",
            operator_workspace_store_path=tmp_path / "workspace.json",
            operational_blob_root=tmp_path / "blobs",
        ),
        overrides=AppDependencyOverrides(model=FakeLanguageModel()),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        create = await client.post(
            "/api/v1/incident-watches",
            json={
                "disaster": "flood",
                "scope": {"kind": "worldwide"},
                "refresh_interval_seconds": 900,
            },
        )
        assert create.status_code == 503
        assert (await client.get("/api/v1/incident-watches")).status_code == 200
        unsupported = await client.post(
            "/api/v1/incident-watches",
            json={
                "disaster": "drought",
                "scope": {"kind": "worldwide"},
                "refresh_interval_seconds": 900,
            },
        )
        assert unsupported.status_code == 422
