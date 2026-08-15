from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.operational_ingestion import (
    SnapshotPersistenceService,
)
from disaster_monitor.domain.disaster import FactStatus, Hazard, SourceAuthority
from disaster_monitor.infrastructure.disaster.cap_adapter import CapAlertAdapter
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.firms_adapter import (
    FirmsActiveFireAdapter,
)
from disaster_monitor.infrastructure.disaster.gfm_adapter import (
    GfmFloodNotificationAdapter,
)
from disaster_monitor.infrastructure.disaster.nchmf_adapter import NchmfWarningAdapter
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.operations.filesystem_blob_store import (
    FilesystemBlobStore,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

NOW = datetime(2026, 8, 13, 3, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
VIETNAM = CATALOG.find_mentions("Vietnam")[0]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _query(hazard: Hazard) -> DisasterQuery:
    return DisasterQuery(hazard, VIETNAM, "recent", ("latest",))


@pytest.mark.asyncio
async def test_nchmf_rss_provides_official_flood_event_and_warning_evidence(
    tmp_path,
) -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel><item>
      <title>TIN CẢNH BÁO LŨ TRÊN SÔNG THAO</title>
      <pubDate>Thu, 13 Aug 2026 02:30:00 GMT</pubDate>
    </item></channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "nchmf.gov.vn"
        return httpx.Response(
            200, text=rss, headers={"content-type": "application/rss+xml"}
        )

    repository = InMemoryOperationalRepository()
    persistence = SnapshotPersistenceService(
        repository, FilesystemBlobStore(tmp_path / "blobs")
    )
    adapter = NchmfWarningAdapter(
        client=_client(handler), snapshot_recorder=persistence.persist
    )
    query = _query(Hazard.FLOOD)

    batch = await adapter.find_recent_events(query, now=NOW)
    reports = await adapter.get_situation_reports(batch.records[0], query, now=NOW)

    assert len(batch.records) == 1
    assert batch.records[0].source.authority == SourceAuthority.NATIONAL_AUTHORITY
    assert batch.records[0].source.source_id == "nchmf-vietnam-warnings"
    assert reports.records[0].facts[0].status == FactStatus.CONFIRMED
    assert reports.records[0].facts[0].category == "official_warning"
    assert "No unreported impact" in reports.records[0].narrative
    assert len(repository.snapshot_records) == 1
    snapshot = next(iter(repository.snapshot_records.values()))
    assert snapshot.rights_id == "nchmf-rss-terms-2026-08"
    assert snapshot.payload_sha256.startswith("sha256:")


@pytest.mark.asyncio
async def test_firms_detection_remains_satellite_observation_not_incident_claim() -> (
    None
):
    csv = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
        "satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        "21.03,105.85,330.4,0.4,0.4,2026-08-13,0130,N20,VIIRS,h,2.0NRT,"
        "295.6,12.5,D\n"
        "1.0,1.0,330.4,0.4,0.4,2026-08-13,0130,N20,VIIRS,h,2.0NRT,"
        "295.6,10.0,D\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "test-map-key" in request.url.path
        return httpx.Response(200, text=csv, headers={"content-type": "text/csv"})

    adapter = FirmsActiveFireAdapter(
        geography=CATALOG,
        map_key="test-map-key",
        client=_client(handler),
    )
    query = _query(Hazard.WILDFIRE)

    batch = await adapter.find_recent_events(query, now=NOW)
    reports = await adapter.get_situation_reports(batch.records[0], query, now=NOW)

    assert len(batch.records) == 1
    assert batch.records[0].source.authority == SourceAuthority.SCIENTIFIC_AUTHORITY
    assert batch.records[0].significance == 12.5
    assert reports.records[0].facts[0].label == "NASA FIRMS active-fire detection"
    assert "not an official wildfire incident declaration" in (
        reports.records[0].narrative
    )


@pytest.mark.asyncio
async def test_gfm_notification_is_analytical_flood_product() -> None:
    payload = {
        "push_notifications": [
            {
                "user_id": "configured-user",
                "aoi_id": "vietnam-aoi",
                "aoi_name": "Red River Delta",
                "product_id": "gfm-product-7",
                "product_time": "2026-08-13T01:00:00+00:00",
                "notification_seen": False,
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer configured-token"
        return httpx.Response(
            200, json=payload, headers={"content-type": "application/json"}
        )

    adapter = GfmFloodNotificationAdapter(
        access_token="configured-token",
        user_id="configured-user",
        client=_client(handler),
    )
    query = _query(Hazard.FLOOD)

    batch = await adapter.find_recent_events(query, now=NOW)
    reports = await adapter.get_situation_reports(batch.records[0], query, now=NOW)

    assert batch.records[0].event_id == "gfm:vietnam-aoi:gfm-product-7"
    assert reports.records[0].facts[0].status == FactStatus.ESTIMATED
    assert reports.records[0].facts[0].category == "analytical_flood_product"
    assert "not a national warning" in reports.records[0].narrative


@pytest.mark.asyncio
async def test_cap_adapter_accepts_only_public_actual_hazard_matched_alerts() -> None:
    cap = """<?xml version="1.0" encoding="UTF-8"?>
    <alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <identifier>flood-2026-7</identifier>
      <sender>alerts@example.gov</sender>
      <sent>2026-08-13T02:00:00+00:00</sent>
      <status>Actual</status><msgType>Alert</msgType><scope>Public</scope>
      <info><event>River Flood Warning</event><urgency>Immediate</urgency>
        <severity>Severe</severity><certainty>Likely</certainty>
        <headline>Severe river flood warning</headline>
        <description>Observed river levels are rising.</description>
        <instruction>Follow instructions from the issuing authority.</instruction>
        <area><areaDesc>Red River Delta</areaDesc>
          <polygon>21.0,105.0 21.0,106.0 20.0,106.0 21.0,105.0</polygon>
        </area>
      </info>
    </alert>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=cap, headers={"content-type": "application/cap+xml"}
        )

    adapter = CapAlertAdapter(
        provider_name="Reviewed example authority",
        source_id="reviewed-example-cap",
        publisher="Reviewed Example Authority",
        feed_url="https://alerts.example.gov/cap.xml",
        allowed_hosts=frozenset({"alerts.example.gov"}),
        rights_id="reviewed-example-cap-rights",
        client=_client(handler),
    )
    query = _query(Hazard.FLOOD)

    batch = await adapter.find_recent_events(query, now=NOW)
    reports = await adapter.get_situation_reports(batch.records[0], query, now=NOW)

    assert len(batch.records) == 1
    assert batch.records[0].intensity == "Severe"
    assert reports.records[0].facts[0].category == "official_warning"
    assert "not a DisasterMonitor directive" in reports.records[0].narrative

    mismatch = await adapter.find_recent_events(_query(Hazard.WILDFIRE), now=NOW)
    assert not mismatch.records


def test_cap_authority_rejects_non_https_or_unregistered_network_target() -> None:
    with pytest.raises(
        DisasterProviderResponseError, match="outside the approved source authority"
    ):
        CapAlertAdapter(
            provider_name="Unsafe",
            source_id="unsafe-cap",
            publisher="Unsafe",
            feed_url="http://alerts.example.gov/cap.xml",
            allowed_hosts=frozenset({"alerts.example.gov"}),
            rights_id="unsafe-rights",
        )
