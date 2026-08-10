"""Deterministic FastAPI server used by the Playwright system test."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn

api_src = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
sys.path.insert(0, str(api_src))

from disaster_monitor.application.disaster import ProviderBatch  # noqa: E402
from disaster_monitor.application.dto import (  # noqa: E402
    ModelReadiness,
    ModelRequest,
)
from disaster_monitor.application.services.current_disaster_report import (  # noqa: E402
    CurrentDisasterReportService,
)
from disaster_monitor.domain.disaster import (  # noqa: E402
    DisasterEvent,
    FactStatus,
    Hazard,
    ReportedFact,
    SituationReport,
    SourceReference,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (  # noqa: E402
    StaticCountryCatalog,
)
from disaster_monitor.main import create_app  # noqa: E402

NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
TARGET_TIME = datetime(2026, 8, 5, 14, 30, tzinfo=UTC)
FOREIGN_SENTINEL = "VENEZUELA-FOREIGN-EVIDENCE-SENTINEL"
UNRELATED_SENTINEL = "TOKYO-UNRELATED-EVIDENCE-SENTINEL"
MODEL_SENTINEL = "GENERAL-MODEL-SENTINEL"
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
VENEZUELA = CATALOG.get_by_alpha3("VEN")
assert JAPAN is not None and VENEZUELA is not None


class FakeSystemModel:
    async def generate(self, _request: ModelRequest):
        raise AssertionError(f"{MODEL_SENTINEL}: source-backed request reached model")

    async def check_readiness(self) -> ModelReadiness:
        return ModelReadiness(True, True, "fake-qwen")


class FakeSystemEventProvider:
    async def find_recent_events(self, _query, *, now):
        jma_source = SourceReference(
            source_id="system-jma-events",
            publisher="JMA fixture",
            title="Deterministic JMA Japan earthquake event",
            canonical_url="https://example.test/system-jma-event",
            published_at=TARGET_TIME,
            updated_at=now - timedelta(minutes=10),
            retrieved_at=now,
        )
        usgs_source = SourceReference(
            source_id="system-usgs-events",
            publisher="USGS fixture",
            title="Deterministic USGS Japan earthquake event",
            canonical_url="https://example.test/system-usgs-event",
            published_at=TARGET_TIME,
            updated_at=now - timedelta(minutes=5),
            retrieved_at=now,
        )
        unrelated_source = SourceReference(
            source_id="system-usgs-events",
            publisher="USGS fixture",
            title="Unrelated Tokyo earthquake event",
            canonical_url="https://example.test/system-unrelated-event",
            published_at=datetime(2026, 8, 5, 23, 15, tzinfo=UTC),
            updated_at=now - timedelta(minutes=5),
            retrieved_at=now,
        )
        foreign_source = SourceReference(
            source_id="system-usgs-events",
            publisher="USGS fixture",
            title="More significant Venezuela earthquake event",
            canonical_url="https://example.test/system-venezuela-event",
            published_at=datetime(2026, 8, 6, 1, 45, tzinfo=UTC),
            updated_at=now - timedelta(minutes=1),
            retrieved_at=now,
        )
        return ProviderBatch(
            (
                DisasterEvent(
                    event_id="jma:system-fixture",
                    hazard=Hazard.EARTHQUAKE,
                    location="Ishikawa, Japan",
                    country=JAPAN,
                    event_time=TARGET_TIME,
                    source=jma_source,
                    latitude=37.0,
                    longitude=137.0,
                    magnitude=6.0,
                    intensity="JMA 6-",
                    depth_km=12,
                    significance=400,
                    provider_ids=("jma:system-fixture",),
                ),
                DisasterEvent(
                    event_id="usgs:system-fixture",
                    hazard=Hazard.EARTHQUAKE,
                    location="Ishikawa, Japan",
                    country=JAPAN,
                    event_time=TARGET_TIME + timedelta(seconds=20),
                    source=usgs_source,
                    latitude=37.02,
                    longitude=137.01,
                    magnitude=6.1,
                    depth_km=11,
                    significance=600,
                    provider_ids=("usgs:system-fixture",),
                ),
                DisasterEvent(
                    event_id="usgs:unrelated",
                    hazard=Hazard.EARTHQUAKE,
                    location="Tokyo, Japan",
                    country=JAPAN,
                    event_time=datetime(2026, 8, 5, 23, 15, tzinfo=UTC),
                    source=unrelated_source,
                    latitude=35.7,
                    longitude=139.7,
                    magnitude=9.5,
                    significance=5_000,
                    provider_ids=("usgs:unrelated",),
                ),
                DisasterEvent(
                    event_id="usgs:venezuela-decoy",
                    hazard=Hazard.EARTHQUAKE,
                    location="Sucre, Venezuela",
                    country=VENEZUELA,
                    event_time=datetime(2026, 8, 6, 1, 45, tzinfo=UTC),
                    source=foreign_source,
                    latitude=10.4,
                    longitude=-63.5,
                    magnitude=9.8,
                    significance=6_000,
                    provider_ids=("usgs:venezuela-decoy",),
                ),
            )
        )


class FakeSystemSituationProvider:
    async def get_situation_reports(self, event, _query, *, now):
        source = SourceReference(
            source_id="system-situation-reports",
            publisher="ReliefWeb fixture",
            title="Deterministic situation update",
            canonical_url="https://example.test/system-situation",
            published_at=now - timedelta(minutes=5),
            updated_at=now - timedelta(minutes=2),
            retrieved_at=now,
        )
        return ProviderBatch(
            (
                SituationReport(
                    source=source,
                    narrative=(
                        "Four buildings were damaged in Ishikawa; an airport closure "
                        "was reported while officials inspected the area."
                    ),
                    facts=(
                        ReportedFact(
                            category="buildings",
                            label="Buildings damaged",
                            value="4",
                            status=FactStatus.CONFIRMED,
                            source=source,
                            event_id=event.event_id,
                            claim_id="buildings",
                        ),
                        ReportedFact(
                            category="fatalities",
                            label="Fatalities",
                            value="2",
                            status=FactStatus.CONFIRMED,
                            source=source,
                            event_id=event.event_id,
                            claim_id="fatalities",
                        ),
                    ),
                    event_id=event.event_id,
                ),
                SituationReport(
                    source=SourceReference(
                        source_id="system-tsunami-status",
                        publisher="JMA tsunami fixture",
                        title="Official tsunami status for system event",
                        canonical_url="https://example.test/system-tsunami",
                        published_at=now - timedelta(minutes=4),
                        updated_at=now - timedelta(minutes=3),
                        retrieved_at=now,
                    ),
                    narrative="No tsunami warning was issued for the selected event.",
                    facts=(
                        ReportedFact(
                            category="tsunami",
                            label="Tsunami status",
                            value="No tsunami warning issued",
                            status=FactStatus.CONFIRMED,
                            source=SourceReference(
                                source_id="system-tsunami-status",
                                publisher="JMA tsunami fixture",
                                title="Official tsunami status for system event",
                                canonical_url="https://example.test/system-tsunami",
                                published_at=now - timedelta(minutes=4),
                                updated_at=now - timedelta(minutes=3),
                                retrieved_at=now,
                            ),
                            event_id="jma:system-fixture",
                            claim_id="tsunami-status",
                        ),
                    ),
                    event_id="jma:system-fixture",
                ),
                SituationReport(
                    source=source,
                    narrative="Tokyo suffered unrelated damage after another quake.",
                    event_id="usgs:unrelated",
                ),
                SituationReport(
                    source=SourceReference(
                        source_id="system-foreign-reports",
                        publisher="Foreign fixture",
                        title="Venezuela decoy update",
                        canonical_url="https://example.test/system-venezuela-situation",
                        published_at=now - timedelta(minutes=3),
                        updated_at=now - timedelta(minutes=1),
                        retrieved_at=now,
                    ),
                    narrative=f"{FOREIGN_SENTINEL}: foreign impacts were reported.",
                    event_id="usgs:venezuela-decoy",
                    countries=("Venezuela",),
                ),
                SituationReport(
                    source=source,
                    narrative=f"{UNRELATED_SENTINEL}: unrelated Japan event damage.",
                    event_id="usgs:unrelated",
                    countries=("Japan",),
                ),
            )
        )


if __name__ == "__main__":
    uvicorn.run(
        create_app(
            model=FakeSystemModel(),
            current_disaster_report=CurrentDisasterReportService(
                FakeSystemEventProvider(), FakeSystemSituationProvider()
            ),
        ),
        host="127.0.0.1",
        port=8787,
        log_level="warning",
    )
