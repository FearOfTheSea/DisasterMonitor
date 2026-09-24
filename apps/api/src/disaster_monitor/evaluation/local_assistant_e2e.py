"""Small, source-anchored live assistant regression runner."""

import argparse
import asyncio
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import httpx


def _place_matches(location: str, place: str) -> bool:
    def fold(value: str) -> str:
        plain = "".join(
            character
            for character in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(character)
        )
        return " ".join(re.sub(r"[^\w]+", " ", plain).split())

    wanted = fold(place)
    return bool(
        wanted and re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", fold(location))
    )


def score_case(case: dict[str, Any], response: dict[str, Any]) -> str:
    """Classify a response without treating a candid gap as event recall."""
    source_url_fragment = case["source_url_contains"]
    sources = response.get("sources")
    has_expected_source = isinstance(sources, list) and any(
        isinstance(source, dict)
        and source_url_fragment in str(source.get("canonical_url", ""))
        for source in sources
    )
    selected = response.get("selected_event")
    if not isinstance(selected, dict):
        if response.get("response_type") == "current_disaster_place_unverified":
            investigation = response.get("investigation") or {}
            return (
                "honest_place_gap"
                if has_expected_source
                and investigation.get("place_candidate_count", 0) > 0
                else "unattributed_place_gap"
            )
        return "missed_event"
    if selected.get("event_id") != case["expected_event_id"]:
        return "wrong_event"
    if not has_expected_source:
        return "unattributed_event"
    place = case.get("requested_place")
    if place and not _place_matches(str(selected.get("location", "")), str(place)):
        return "unverified_place_attribution"
    answer = str(response.get("answer") or "").casefold()
    if any(
        str(unrelated_place).casefold() in answer
        for unrelated_place in case.get("answer_excludes", [])
    ):
        return "wrong_place_impact"
    return "verified_event"


async def evaluate_cases(
    cases: list[dict[str, Any]], *, api_url: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=900) as client:
        for case in cases:
            try:
                response = await client.post(
                    f"{api_url.rstrip('/')}/api/v1/assistant",
                    json={"question": case["question"]},
                )
                response.raise_for_status()
                payload = response.json()
                verdict = score_case(case, payload)
                investigation = payload.get("investigation") or {}
                results.append(
                    {
                        "id": case["id"],
                        "verdict": verdict,
                        "response_type": payload.get("response_type"),
                        "selected_event_id": (payload.get("selected_event") or {}).get(
                            "event_id"
                        ),
                        "event_issue_codes": investigation.get("event_issue_codes", []),
                        "event_records_seen": investigation.get("event_records_seen"),
                        "event_scan_complete": investigation.get("event_scan_complete"),
                        "place_candidate_count": investigation.get(
                            "place_candidate_count"
                        ),
                        "source_urls": [
                            source.get("canonical_url")
                            for source in payload.get("sources", [])
                        ],
                    }
                )
            except (httpx.HTTPError, ValueError, KeyError) as error:
                results.append(
                    {"id": case["id"], "verdict": "request_error", "error": str(error)}
                )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_file", type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8002")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.case_file.read_text(encoding="utf-8"))["cases"]
    results = asyncio.run(evaluate_cases(cases, api_url=args.api_url))
    output = json.dumps({"results": results}, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    if any(result["verdict"] != "verified_event" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
