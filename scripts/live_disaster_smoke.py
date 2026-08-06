"""Opt-in structural smoke test for live current-disaster providers."""

import asyncio
import sys
from pathlib import Path

api_src = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
sys.path.insert(0, str(api_src))

from disaster_monitor.application.services.current_disaster_report import (  # noqa: E402
    CurrentDisasterReportService,
)
from disaster_monitor.infrastructure.composition import (  # noqa: E402
    build_current_disaster_report,
    build_disaster_query_parser,
)
from disaster_monitor.infrastructure.disaster.composite import (  # noqa: E402
    CompositeDisasterEventProvider,
    CompositeSituationReportProvider,
)
from disaster_monitor.infrastructure.configuration import Settings  # noqa: E402

QUESTIONS = (
    "Give me latest information on earthquake in Japan.",
    "Give me the latest information on the July 28, 2026 Kumamoto earthquake in Japan.",
)


def _print_provider_status(
    label: str, provider, counts: dict[str, int], issues
) -> None:
    issue_by_provider = {issue.provider: issue for issue in issues}
    print(f"{label}_providers=")
    for item in provider.providers:
        name = getattr(item, "provider_name", item.__class__.__name__)
        issue = issue_by_provider.get(name)
        if issue is not None:
            status = f"failed code={issue.reason_code}"
            if issue.http_status is not None:
                status += f" http_status={issue.http_status}"
        else:
            status = "succeeded" if counts.get(name, 0) else "no_records"
        print(f"- {name}: {status} records={counts.get(name, 0)}")


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    settings = Settings()
    query_parser = build_disaster_query_parser()
    for question in QUESTIONS:
        service: CurrentDisasterReportService = build_current_disaster_report(settings)
        try:
            query = query_parser.parse(question).query
            if query is None:
                raise RuntimeError(
                    f"Could not normalize live smoke question: {question}"
                )
            result = await service.execute(query)
            event_provider = service._event_provider  # noqa: SLF001
            situation_provider = service._situation_report_provider  # noqa: SLF001
            if isinstance(event_provider, CompositeDisasterEventProvider):
                _print_provider_status(
                    "event",
                    event_provider,
                    event_provider.last_record_counts,
                    event_provider.last_diagnostics,
                )
            if isinstance(situation_provider, CompositeSituationReportProvider):
                _print_provider_status(
                    "situation",
                    situation_provider,
                    situation_provider.last_record_counts,
                    situation_provider.last_diagnostics,
                )
                if not settings.reliefweb_app_name:
                    print("- ReliefWeb: skipped (not configured)")
        finally:
            await service.aclose()
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
                f"- {source.publisher}: {source.canonical_url} latest={timestamp.isoformat()}"
            )
        for warning in result.warnings:
            print(f"warning={warning}")


if __name__ == "__main__":
    asyncio.run(main())
