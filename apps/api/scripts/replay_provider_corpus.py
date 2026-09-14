"""Run the locked provider replay gate without network access."""

import argparse
import json
from pathlib import Path

from disaster_monitor.evaluation.provider_replay import replay_provider_corpus
from disaster_monitor.evaluation.reproducibility import ReproducibilityError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPOSITORY_ROOT / "evaluation" / "provider_reference_corpus.v1.json",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        report = replay_provider_corpus(arguments.corpus.resolve())
    except (OSError, ReproducibilityError, ValueError) as error:
        print(f"Provider replay failed closed: {error}")
        return 2
    encoded = json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.resolve().write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report.deterministic and report.promotion_eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())
