"""Lock an owner-curated DisasterAgentBench selection without downloading data."""

import argparse
import json
from pathlib import Path

from disaster_monitor.evaluation.disaster_agent_bench import (
    lock_selection,
)
from disaster_monitor.evaluation.reproducibility import ReproducibilityError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged-root", required=True, type=Path)
    parser.add_argument("--selection-file", required=True, type=Path)
    parser.add_argument("--output-manifest", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        manifest = lock_selection(arguments.staged_root, arguments.selection_file)
        output = arguments.output_manifest.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except (
        ReproducibilityError,
        OSError,
        ValueError,
    ) as error:
        print(f"DisasterAgentBench preparation failed closed: {error}")
        return 2
    print(
        f"Locked {len(manifest['episodes'])} episodes at {output} "
        f"({manifest['manifest_sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
