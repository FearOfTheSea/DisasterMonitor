"""Optional real-Qwen smoke test for a running local API and Ollama model."""

import json
import os
import sys

import httpx


def main() -> int:
    base_url = os.getenv("DISASTER_MONITOR_API_URL", "http://127.0.0.1:8001/api/v1")
    with httpx.Client(timeout=90.0) as client:
        readiness = client.get(f"{base_url}/ready")
        readiness.raise_for_status()
        payload = readiness.json()
        print(json.dumps(payload, indent=2))
        if not payload.get("ollama_available") or not payload.get("model_available"):
            print("The configured local Qwen model is not ready.", file=sys.stderr)
            return 1

        response = client.post(
            f"{base_url}/assistant",
            json={"question": "What can I use this disaster map for?"},
        )
        response.raise_for_status()
        print(json.dumps(response.json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
