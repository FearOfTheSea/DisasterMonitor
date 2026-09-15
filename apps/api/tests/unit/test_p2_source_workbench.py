import pytest

from disaster_monitor.application.source_intelligence import (
    CandidateSourceProbeResult,
    CandidateSourceStatus,
    CandidateSourceSubmission,
)
from disaster_monitor.application.sources.source_scouting import (
    SourceCandidateWorkbench,
    SourceScout,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.sources.candidate_store import (
    InMemoryCandidateSourceStore,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)


class _Probe:
    async def inspect(self, homepage_url: str, *, license_url: str | None):
        return CandidateSourceProbeResult(
            reachable=True,
            status_code=200,
            content_type="application/json",
            top_level_fields=("events", "updated_at"),
            license_reachable=license_url == "https://publisher.example/terms",
            checked_url=homepage_url,
        )


@pytest.mark.asyncio
async def test_candidate_workbench_checks_endpoint_schema_and_terms_before_review() -> (
    None
):
    store = InMemoryCandidateSourceStore()
    inspection = await SourceCandidateWorkbench(
        SourceScout(StaticSourceCatalog(), store), _Probe()
    ).inspect(
        CandidateSourceSubmission(
            candidate_id="publisher-feed",
            display_name="Publisher feed",
            homepage_url="https://publisher.example/feed.json",
            content_signals=("event_feed",),
            disasters=(Disaster.FLOOD,),
            claimed_domain="publisher.example",
            expected_fields=("events", "updated_at"),
            license_url="https://publisher.example/terms",
        )
    )

    assert inspection.record.status is CandidateSourceStatus.AWAITING_HUMAN_APPROVAL
    assert inspection.schema_matches is True
    assert inspection.license_terms_available is True
    assert inspection.ready_for_human_review is True
    assert inspection.findings == ()
    assert StaticSourceCatalog().get("publisher-feed") is None
