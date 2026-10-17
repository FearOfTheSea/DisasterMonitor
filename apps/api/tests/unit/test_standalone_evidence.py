from datetime import UTC, datetime

import pytest

from disaster_monitor.application.evidence.standalone import StandaloneEvidenceService
from disaster_monitor.application.media import MediaEventContext
from disaster_monitor.application.ports.standalone_evidence import (
    IncidentEvidenceContext,
)
from disaster_monitor.domain.disaster_types import Disaster

NOW = datetime(2026, 10, 11, tzinfo=UTC)


class Contexts:
    async def read(self, identifier):
        return IncidentEvidenceContext(
            media=MediaEventContext(
                identifier,
                "physical:test",
                Disaster.FLOOD,
                "Offshore",
                NOW,
                (),
                None,
                (),
                0,
                0,
            ),
            event=None,
            geometry=None,
        )


@pytest.mark.asyncio
async def test_countryless_event_does_not_invent_country_or_impacts():
    service = StandaloneEvidenceService(Contexts(), clock=lambda: NOW)
    result = await service.execute("test", "impacts")
    assert result.state == "empty"
    assert not result.facts
    assert "country_unresolved" in result.reason_codes


@pytest.mark.asyncio
async def test_missing_datasets_are_unconfigured_not_zero_exposure():
    service = StandaloneEvidenceService(Contexts(), clock=lambda: NOW)
    result = await service.execute("test", "exposure")
    assert result.state == "unconfigured"
    assert result.exposure is None


@pytest.mark.asyncio
async def test_sections_are_independent_without_model():
    service = StandaloneEvidenceService(Contexts(), clock=lambda: NOW)
    assert (await service.execute("test", "media")).state == "unconfigured"
    assert (await service.execute("test", "warnings")).state == "unconfigured"
    with pytest.raises(ValueError):
        await service.execute("test", "assistant")


class CountryContexts:
    async def read(self, identifier):
        from disaster_monitor.domain.disaster import (
            Country,
            DisasterEvent,
            GeographicArea,
            SourceReference,
        )

        source = SourceReference(
            "gdacs-floods",
            "GDACS",
            "Flood in River Town",
            "https://www.gdacs.org/report/1",
            NOW,
            NOW,
            NOW,
        )
        event = DisasterEvent(
            "gdacs:fl:1",
            Disaster.FLOOD,
            "River Town",
            Country("VNM", "Vietnam", (), GeographicArea(8, 24, 102, 110)),
            NOW,
            source,
            provider_ids=("gdacs:fl:1",),
        )
        media = MediaEventContext(
            event.event_id,
            "physical:flood:1",
            event.disaster,
            event.location,
            NOW,
            event.provider_ids,
            "VNM",
            ("Vietnam",),
            10,
            106,
        )
        return IncidentEvidenceContext(media, event, None)


async def test_event_specific_impacts_are_available_without_assistant_messages():
    from disaster_monitor.application.disaster import ProviderBatch
    from disaster_monitor.domain.disaster import (
        FactStatus,
        ReportedFact,
        SituationReport,
    )

    context = await CountryContexts().read("selected")

    class Reports:
        async def get_situation_reports(self, event, query, *, now):
            return ProviderBatch(
                (
                    SituationReport(
                        context.event.source,
                        "2 homes damaged in River Town.",
                        facts=(
                            ReportedFact(
                                "buildings",
                                "Damaged homes",
                                "2",
                                FactStatus.PRELIMINARY,
                                context.event.source,
                                event_id=event.event_id,
                                observed_at=NOW,
                            ),
                        ),
                        event_id=event.event_id,
                        disaster=event.disaster,
                    ),
                )
            )

    result = await StandaloneEvidenceService(
        CountryContexts(), situation=Reports(), clock=lambda: NOW
    ).execute("selected", "impacts")
    assert result.state in ("available", "degraded")
    assert result.facts[0].value == "2"
    assert result.facts[0].source.publisher == "GDACS"


async def test_broad_country_report_cannot_become_impacts_from_requested_fact_id():
    from dataclasses import replace

    from disaster_monitor.application.disaster import ProviderBatch
    from disaster_monitor.domain.disaster import (
        FactStatus,
        ReportedFact,
        SituationReport,
    )

    context = await CountryContexts().read("selected")
    source = replace(
        context.event.source,
        source_id="reliefweb-reports",
        publisher="ReliefWeb",
        title="Regional humanitarian overview",
    )

    class Reports:
        async def get_situation_reports(self, event, query, *, now):
            return ProviderBatch(
                (
                    SituationReport(
                        source,
                        "A country-wide review reports 500 homes damaged.",
                        facts=(
                            ReportedFact(
                                "buildings",
                                "Damaged homes",
                                "500",
                                FactStatus.PRELIMINARY,
                                source,
                                event_id=event.event_id,
                            ),
                        ),
                        countries=("Vietnam",),
                        disaster=event.disaster,
                    ),
                )
            )

    result = await StandaloneEvidenceService(
        CountryContexts(), situation=Reports(), clock=lambda: NOW
    ).execute("selected", "impacts")
    assert result.facts == ()
    assert result.narratives == ()
    assert any("excluded" in detail for detail in result.limitations)


async def test_unrelated_warnings_are_excluded_but_explicit_reference_is_retained():
    from dataclasses import replace
    from datetime import timedelta

    from disaster_monitor.application.ports.weather_alerts import WeatherAlertBatch
    from disaster_monitor.domain.warnings import (
        CapAlert,
        CapInfo,
        CapMessageType,
        CapScope,
        CapStatus,
        WarningCertainty,
        WarningSeverity,
        WarningUrgency,
    )

    info = CapInfo(
        "en",
        ("Met",),
        "Flood Warning",
        (),
        WarningUrgency.EXPECTED,
        WarningSeverity.SEVERE,
        WarningCertainty.LIKELY,
        NOW,
        NOW,
        NOW + timedelta(hours=2),
        "Official authority",
        "Flood Warning",
        "Source warning",
        "Follow local instructions",
        (),
    )
    unrelated = CapAlert(
        "US-warning",
        "authority.example",
        NOW,
        CapStatus.ACTUAL,
        CapMessageType.ALERT,
        CapScope.PUBLIC,
        "fixture-cap",
        "Official authority",
        (info,),
        NOW,
        "Source attribution",
        (),
        incidents=("unrelated:1",),
    )
    matching = replace(unrelated, identifier="matching", incidents=("gdacs:fl:1",))

    class Warnings:
        async def current_messages(self):
            return WeatherAlertBatch((unrelated, matching))

    result = await StandaloneEvidenceService(
        CountryContexts(), warnings=Warnings(), clock=lambda: NOW
    ).execute("selected", "warnings")
    assert [item.alert.identifier for item in result.warnings] == ["matching"]
    assert result.warnings[0].association.confirmed


async def test_operator_inspection_is_explicit_and_point_is_not_a_source_footprint():
    from disaster_monitor.application.exposure.analysis import ExposureAnalysisService

    service = StandaloneEvidenceService(
        CountryContexts(), exposure=ExposureAnalysisService(), clock=lambda: NOW
    )
    assert (await service.execute("selected", "exposure")).reason_codes == (
        "supported_geometry_missing",
    )
    result = await service.execute_inspection("selected", (105.95, 9.95, 106.05, 10.05))
    assert result.exposure.geometry.role.value == "operator_inspection"
    assert "operator inspection area" in result.exposure.display_label.lower()
    with pytest.raises(ValueError, match="bounded"):
        await service.execute_inspection("selected", (-180, -90, 180, 90))


async def test_empty_failed_source_is_degraded_instead_of_no_impacts():
    from disaster_monitor.application.disaster import ProviderBatch, ProviderIssue

    class FailedReports:
        async def get_situation_reports(self, event, query, *, now):
            return ProviderBatch(
                issues=(
                    ProviderIssue(
                        "fixture",
                        "Unavailable",
                        reason_code="timeout",
                        retryable=True,
                        detail="Source timed out.",
                    ),
                )
            )

    result = await StandaloneEvidenceService(
        CountryContexts(), situation=FailedReports(), clock=lambda: NOW
    ).execute("selected", "impacts")
    assert result.state == "degraded"
    assert not result.facts
    assert "Source timed out." in result.limitations


async def test_retained_section_is_backed_off_after_failed_refresh():
    from datetime import timedelta

    from disaster_monitor.application.media import DisasterMediaGallery

    current = [NOW]

    class Media:
        calls = 0

        async def discover(self, context):
            self.calls += 1
            if self.calls > 1:
                raise TimeoutError()
            return DisasterMediaGallery(
                context.event_id, context.physical_event_id, NOW, (), (), 0
            )

    media = Media()
    service = StandaloneEvidenceService(
        Contexts(), media=media, clock=lambda: current[0]
    )
    first = await service.execute("selected", "media")
    current[0] += timedelta(minutes=6)
    second = await service.execute("selected", "media")
    third = await service.execute("selected", "media")
    assert second.state == "degraded"
    assert second.retrieved_at == first.retrieved_at
    assert third == second
    assert media.calls == 2
