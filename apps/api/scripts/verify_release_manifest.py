"""Verify a locked DisasterAgentBench manifest, labels, rights, and payloads."""

import argparse
from pathlib import Path

from disaster_monitor.evaluation.disaster_agent_bench import (
    validate_locked_manifest,
)
from disaster_monitor.evaluation.reproducibility import ReproducibilityError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        manifest, episodes = validate_locked_manifest(arguments.manifest)
    except (
        ReproducibilityError,
        OSError,
        ValueError,
    ) as error:
        print(f"Release manifest verification failed closed: {error}")
        return 2
    print(
        f"Verified {manifest['manifest_id']} ({manifest['manifest_sha256']}): "
        f"{len(episodes)} episodes, "
        f"{sum(len(item.snapshots) for item in episodes)} immutable snapshots"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
