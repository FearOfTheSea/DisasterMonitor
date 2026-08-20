"""Opt-in structural smoke test for every live event-discovery capability."""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

api_src = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
sys.path.insert(0, str(api_src))

from disaster_monitor.application.agent.task_normalization import (
    worldwide_disaster_query,
)
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.composition import (
    build_country_catalog,
    build_current_disaster_report,
    build_disaster_query_parser,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
    CompositeSituationReportProvider,
)


@dataclass(frozen=True, slots=True)
class LiveSmokeCase:
    disaster: Disaster
    named_country_questions: tuple[str, str]
    worldwide_question: str


CASES = (
    LiveSmokeCase(
        Disaster.EARTHQUAKE,
        (
            "Give me the latest earthquake information in Japan.",
            "Give me the latest earthquake information in Chile.",
        ),
        "What recent earthquakes were reported worldwide?",
    ),
    LiveSmokeCase(
        Disaster.FLOOD,
        (
            "Give me the latest flood information in the Philippines.",
            "Give me the latest flood information in Pakistan.",
        ),
        "What recent floods were reported worldwide?",
    ),
    LiveSmokeCase(
        Disaster.WILDFIRE,
        (
            "Give me the latest wildfire information in the United States.",
            "Give me the latest wildfire information in Australia.",
        ),
        "What recent wildfires were reported worldwide?",
    ),
    LiveSmokeCase(
        Disaster.LANDSLIDE,
        (
            "Give me the latest landslide information in Nepal.",
            "Give me the latest landslide information in Pakistan.",
        ),
        "What recent landslides were reported worldwide?",
    ),
    LiveSmokeCase(
        Disaster.TROPICAL_CYCLONE,
        (
            "Give me the latest tropical cyclone information in the Philippines.",
            "Give me the latest tropical cyclone information in Japan.",
        ),
        "What recent tropical cyclones were reported worldwide?",
    ),
    LiveSmokeCase(
        Disaster.VOLCANIC_ERUPTION,
        (
            "Give me the latest volcanic eruption information in Indonesia.",
            "Give me the latest volcanic eruption information in the United States.",
        ),
        "What recent volcanic eruptions were reported worldwide?",
    ),
)


def _print_provider_status(
    label: str, provider: object, counts: dict[str, int], issues: tuple[object, ...]
) -> None:
    issue_by_provider = {
        issue.provider: issue
        for issue in issues
        if hasattr(issue, "provider") and hasattr(issue, "reason_code")
    }
    print(f"{label}_providers=")
    for item in provider.providers:
        name = getattr(item, "provider_name", item.__class__.__name__)
        issue = issue_by_provider.get(name)
        if issue is not None:
            status = f"degraded code={issue.reason_code}"
            if issue.http_status is not None:
                status += f" http_status={issue.http_status}"
        else:
            status = "succeeded" if counts.get(name, 0) else "no_records"
        print(f"- {name}: {status} records={counts.get(name, 0)}")


def _print_report(scope: str, question: str, result: object) -> None:
    print(f"scope={scope}")
    print(f"question={question}")
    print(f"response_type={result.response_type}")
    if result.selected_event is not None:
        print(
            f"event={result.selected_event.event_id} {result.selected_event.location}"
        )
        print(f"event_provider_ids={','.join(result.selected_event.provider_ids)}")
    print(f"retrieved_at={result.retrieval_time.isoformat()}")
    print("sources=")
    for source in result.sources:
        timestamp = source.updated_at or source.published_at or source.retrieved_at
        print(
            f"- {source.publisher}: {source.canonical_url} "
            f"latest={timestamp.isoformat()}"
        )
    for warning in result.warnings:
        print(f"warning={warning}")


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    settings = Settings()
    country_catalog = build_country_catalog(settings)
    query_parser = build_disaster_query_parser(country_catalog)
    service: CurrentDisasterReportService = build_current_disaster_report(
        settings, country_catalog
    )
    try:
        worldwide_service = WorldwideDisasterReportService(service.provider_registry)
        for case in CASES:
            for named_country_question in case.named_country_questions:
                named_query = query_parser.parse(named_country_question).query
                if named_query is None or named_query.disaster is not case.disaster:
                    raise RuntimeError(
                        "Could not normalize named-country live smoke question: "
                        f"{named_country_question}"
                    )
                named_result = await service.execute(named_query)
                event_provider = service._event_provider
                situation_provider = service._situation_report_provider
                if isinstance(event_provider, CompositeDisasterEventProvider):
                    _print_provider_status(
                        "named_event",
                        event_provider,
                        event_provider.last_record_counts,
                        event_provider.last_diagnostics,
                    )
                if isinstance(situation_provider, CompositeSituationReportProvider):
                    _print_provider_status(
                        "named_situation",
                        situation_provider,
                        situation_provider.last_record_counts,
                        situation_provider.last_diagnostics,
                    )
                _print_report("named_country", named_country_question, named_result)

            worldwide_query = worldwide_disaster_query(case.worldwide_question)
            if worldwide_query is None or worldwide_query.disaster is not case.disaster:
                raise RuntimeError(
                    "Could not normalize worldwide live smoke question: "
                    f"{case.worldwide_question}"
                )
            worldwide_result = await worldwide_service.execute(worldwide_query)
            _print_report("worldwide", case.worldwide_question, worldwide_result)

        snapshot = await ActiveIncidentsService(service.provider_registry).execute()
        print(f"active_incidents_retrieved_at={snapshot.retrieved_at.isoformat()}")
        print(f"active_incidents_count={len(snapshot.incidents)}")
        for coverage in snapshot.coverage:
            print(
                f"active_incidents_coverage={coverage.disaster.value} "
                f"state={coverage.state.value} incidents={coverage.incident_count}"
            )
        for warning in snapshot.warnings:
            print(f"active_incidents_warning={warning}")
    finally:
        await service.aclose()


if __name__ == "__main__":
    asyncio.run(main())
