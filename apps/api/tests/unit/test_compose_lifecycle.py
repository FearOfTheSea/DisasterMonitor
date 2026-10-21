"""Protect the restart policy of long-running Compose services."""

import json
import subprocess
from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[4] / "compose.yaml"
LOCAL_MODEL_COMPOSE_FILE = (
    Path(__file__).resolve().parents[4] / "compose.local-model.yaml"
)


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


def test_model_is_private_gpu_service_and_api_waits_for_model_pull() -> None:
    default_result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    default_services = json.loads(default_result.stdout)["services"]
    assert "ollama" not in default_services
    assert "ollama-pull" not in default_services

    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-f",
            str(LOCAL_MODEL_COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]
    ollama = services["ollama"]

    assert ollama["image"] == "ollama/ollama:0.33.2"
    assert "ports" not in ollama
    assert any(
        mount["source"] == "ollama-models" and mount["target"] == "/root/.ollama"
        for mount in ollama["volumes"]
    )
    assert ollama["deploy"]["resources"]["reservations"]["devices"][0][
        "capabilities"
    ] == ["gpu"]
    assert services["ollama-pull"]["command"] == [
        "pull",
        "qwen3:4b-instruct-2507-q4_K_M",
    ]
    assert services["ollama-pull-vision"]["command"] == ["pull", "qwen3-vl:2b"]
    for service in ("api", "worker"):
        assert services[service]["environment"]["MODEL_PROVIDER"] == "ollama"
        assert services[service]["environment"]["OLLAMA_BASE_URL"] == "http://ollama:11434"
        assert services[service]["environment"]["OLLAMA_MODEL"] == (
            "qwen3:4b-instruct-2507-q4_K_M"
        )
        assert services[service]["depends_on"]["ollama-pull"]["condition"] == (
            "service_completed_successfully"
        )
        assert services[service]["depends_on"]["ollama-pull-vision"]["condition"] == (
            "service_completed_successfully"
        )
