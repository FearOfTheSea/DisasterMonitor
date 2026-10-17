"""Controlled discovery scenarios for desktop system verification, never live data."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

from system_test_backend import NOW

from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryBatch,
    ReportingInterval,
)
from disaster_monitor.domain.events import (
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)


class SystemDiscoveryFeed:
    source_id = "controlled-system-discovery"

    async def discover(
        self, *, interval: ReportingInterval
    ) -> AsyncIterator[DiscoveryBatch]:
        await asyncio.sleep(3)
        if interval.days == 1:
            yield DiscoveryBatch(successful_operations=1)
            return
        if interval.days == 3:
            yield DiscoveryBatch(
                failed_operations=1, issues=("Controlled provider failure.",)
            )
            return
        source = SourceReference(
            "fixture-international-news",
            "Controlled International News",
            "Fixture flood near Riverton",
            "https://fixture.example/flood",
            NOW,
            None,
            NOW,
        )
        geometry = EventGeometry(
            kind=EventGeometryKind.POINT,
            coordinates=(EventCoordinate(35.6, 138.7),),
            source=source,
        )
        yield DiscoveryBatch(
            successful_operations=1,
            articles=(
                DiscoveryArticle(
                    source,
                    "Officials report two people died in the flood.",
                    indexed_at=NOW,
                    event_time=NOW - timedelta(days=60),
                    location="Riverton",
                    geometry=geometry,
                    event_key="fixture:flood-1",
                ),
                DiscoveryArticle(
                    SourceReference(
                        "fixture-international-news",
                        "Controlled International News",
                        "Fixture drought in Unresolved Valley",
                        "https://fixture.example/drought",
                        NOW,
                        None,
                        NOW,
                    ),
                    "Officials report three people died in the drought.",
                    indexed_at=NOW,
                ),
            ),
        )
        if interval.days in (14, 30):
            yield DiscoveryBatch(
                failed_operations=1 if interval.days == 14 else 0,
                truncated=interval.days == 30,
                issues=(
                    "Controlled partial failure."
                    if interval.days == 14
                    else "Controlled acquisition truncation.",
                ),
            )


def build_system_discovery(store: FileDiscoveryStore) -> DiscoveryScanService:
    return DiscoveryScanService((SystemDiscoveryFeed(),), store, clock=lambda: NOW)
