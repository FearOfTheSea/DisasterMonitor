"""Reassess a retained live scan offline; never count replay as new discovery."""

import argparse
import json
from collections import Counter
from pathlib import Path

from pydantic import TypeAdapter

from disaster_monitor.domain.discovery import (
    DiscoveryRun,
    assess_article,
    group_reports,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = TypeAdapter(DiscoveryRun).validate_json(args.input.read_bytes())
    assessed = tuple(
        assess_article(report.article, run.interval) for report in run.reports
    )
    result = {
        "kind": "offline replay of retained live reports; no network or new discovery",
        "scan_id": run.scan_id,
        "interval": {
            "start": run.interval.start.isoformat(),
            "end": run.interval.end.isoformat(),
        },
        "before": dict(Counter(report.eligibility for report in run.reports)),
        "after": dict(Counter(report.eligibility for report in assessed)),
        "replayed_event_records": len(group_reports(assessed)),
        "fatality_report_counts": {
            "before": sum(bool(report.fatality_evidence) for report in run.reports),
            "after": sum(bool(report.fatality_evidence) for report in assessed),
        },
        "changed_fatality_report_urls": [
            old.article.source.canonical_url
            for old, new in zip(run.reports, assessed, strict=True)
            if old.fatality_evidence != new.fatality_evidence
        ],
        "changed_reports": [
            {
                "title": old.article.source.title,
                "url": old.article.source.canonical_url,
                "before": old.eligibility,
                "after": new.eligibility,
                "disaster_before": old.disaster,
                "disaster_after": new.disaster,
            }
            for old, new in zip(run.reports, assessed, strict=True)
            if (old.eligibility, old.disaster) != (new.eligibility, new.disaster)
        ],
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "scan_id",
                    "kind",
                    "before",
                    "after",
                    "replayed_event_records",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
