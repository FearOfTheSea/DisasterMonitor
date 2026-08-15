"""Replay one DAB episode in operational or canonical-effective order."""

import argparse
import json
from pathlib import Path

from disaster_monitor.evaluation.disaster_agent_bench import (
    ReplayMode,
    episode_from_manifest,
    replay_episode,
    replay_result_payload,
)
from disaster_monitor.evaluation.reproducibility import ReproducibilityError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--mode", required=True, choices=[item.value for item in ReplayMode]
    )
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    episode_path = arguments.episode.resolve()
    manifest = (
        arguments.manifest.resolve()
        if arguments.manifest is not None
        else episode_path.parents[1] / "locked-release-manifest.json"
    )
    try:
        episode = episode_from_manifest(manifest, episode_path.name)
        result = replay_episode(episode, ReplayMode(arguments.mode))
        output = arguments.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(replay_result_payload(result), indent=2) + "\n",
            encoding="utf-8",
        )
    except (
        ReproducibilityError,
        OSError,
        ValueError,
        IndexError,
    ) as error:
        print(f"Ingestion replay failed closed: {error}")
        return 2
    print(
        f"Replayed {result.episode_id} in {result.mode.value}; "
        f"canonical state {result.canonical_state_hash}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
