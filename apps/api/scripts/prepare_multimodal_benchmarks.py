"""Lock externally staged MM benchmark slices without downloading them."""

import argparse
import json
from pathlib import Path

from disaster_monitor.evaluation.benchmark_preparation import lock_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged-root", required=True, type=Path)
    parser.add_argument("--selection-file", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        locked = lock_manifest(arguments.staged_root, arguments.selection_file)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"MM benchmark preparation failed closed: {error}")
        return 2
    output = arguments.staged_root.resolve() / "locked-release-manifest.json"
    output.write_text(json.dumps(locked, indent=2) + "\n", encoding="utf-8")
    print(f"Locked {len(locked['samples'])} held-out MM samples at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
