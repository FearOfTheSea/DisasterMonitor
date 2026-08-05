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
)
from disaster_monitor.infrastructure.configuration import Settings  # noqa: E402

QUESTION = (
    "There was a recent earthquake in Japan. Please update me with the latest "
    "information about the damages in Japan."
)


async def main() -> None:
    service: CurrentDisasterReportService = build_current_disaster_report(Settings())
    try:
        result = await service.execute(QUESTION)
    finally:
        await service.aclose()
    if result.selected_event is None:
        raise RuntimeError("No candidate event was returned by the live providers.")
    if not result.sources or not all(
        source.canonical_url.startswith("https://") for source in result.sources
    ):
        raise RuntimeError("The live report did not contain canonical HTTPS sources.")
    if result.retrieval_time is None or result.selected_event.event_time is None:
        raise RuntimeError("The live report did not contain required timestamps.")
    if "Situation summary" not in result.message:
        raise RuntimeError("The live report was not grounded in the report renderer.")
    print(f"response_type={result.response_type}")
    print(f"event={result.selected_event.event_id} {result.selected_event.location}")
    print(f"retrieved_at={result.retrieval_time.isoformat()}")
    print("sources=")
    for source in result.sources:
        print(f"- {source.publisher}: {source.canonical_url}")
    for warning in result.warnings:
        print(f"warning={warning}")


if __name__ == "__main__":
    asyncio.run(main())

