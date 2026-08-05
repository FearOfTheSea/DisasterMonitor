"""Deterministic FastAPI server used by the Playwright system test."""

import sys
from datetime import timedelta
from pathlib import Path

import uvicorn

api_src = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
sys.path.insert(0, str(api_src))

from disaster_monitor.application.disaster import (  # noqa: E402
    DisasterEvent,
    FactStatus,
    ProviderBatch,
    ReportedFact,
    SituationReport,
    SourceReference,
)
from disaster_monitor.application.dto import (  # noqa: E402
    ModelReadiness,
    ModelRequest,
    ModelResponse,
)
from disaster_monitor.application.services.current_disaster_report import (  # noqa: E402
    CurrentDisasterReportService,
)
from disaster_monitor.main import create_app  # noqa: E402


class FakeSystemModel:
    async def generate(self, _request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text="Deterministic system-test response.",
            model="fake-qwen",
        )

    async def check_readiness(self) -> ModelReadiness:
        return ModelReadiness(True, True, "fake-qwen")


class FakeSystemEventProvider:
    async def find_recent_events(self, _query, *, now):
        source = SourceReference(
            publisher="JMA fixture",
            title="Deterministic Japan earthquake event",
            canonical_url="https://example.test/system-event",
            published_at=now - timedelta(hours=2),
            updated_at=now - timedelta(minutes=10),
            retrieved_at=now,
        )
        return ProviderBatch(
            (
                DisasterEvent(
                    event_id="jma:system-fixture",
                    hazard="earthquake",
                    location="Ishikawa, Japan",
                    country="Japan",
                    event_time=now - timedelta(hours=2),
                    source=source,
                    latitude=37.0,
                    longitude=137.0,
                    magnitude=6.1,
                    intensity="JMA 6-",
                    depth_km=12,
                ),
            )
        )


class FakeSystemSituationProvider:
    async def get_situation_reports(self, event, _query, *, now):
        source = SourceReference(
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
                    narrative="Four buildings were damaged in the affected area.",
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
                    ),
                    event_id=event.event_id,
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
