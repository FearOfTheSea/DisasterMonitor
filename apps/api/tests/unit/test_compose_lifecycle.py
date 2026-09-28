"""Protect the restart policy of long-running Compose services."""

import json
import subprocess
from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[4] / "compose.yaml"


def test_long_running_compose_services_have_restart_policy() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]

    for name in ("postgres", "api", "scheduler", "worker", "web"):
        assert services[name]["restart"] == "unless-stopped", name
