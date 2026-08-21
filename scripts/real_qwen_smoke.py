"""Optional real-Qwen smoke test for a running local API and Ollama model."""

import json
import os
import sys

import httpx

LANGUAGE_CASES = (
    ("English", "How many people were killed in the latest earthquake in Indonesia?"),
    (
        "Vietnamese",
        "Có bao nhiêu người thiệt mạng trong trận động đất mới nhất ở Indonesia?",
    ),
    ("Chinese", "印度尼西亚最近的地震造成了多少人死亡？"),
    ("Korean", "인도네시아의 최근 지진으로 몇 명이 사망했나요?"),
    ("Japanese", "インドネシアの最近の地震で何人が亡くなりましたか？"),
)


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

        for language, question in LANGUAGE_CASES:
            response = client.post(
                f"{base_url}/assistant",
                json={"question": question},
                timeout=300.0,
            )
            response.raise_for_status()
            body = response.json()
            print(
                json.dumps(
                    {
                        "language": language,
                        "question": question,
                        "message_prefix": body.get("message", "")[:500],
                        "response_type": body.get("response_type"),
                        "event_id": (body.get("selected_event") or {}).get("event_id"),
                        "source_urls": [
                            source.get("canonical_url")
                            for source in body.get("sources", [])
                        ],
                        "investigation": body.get("investigation"),
                        "warnings": body.get("warnings", []),
                    },
                    ensure_ascii=True,
                )
            )

        degraded = client.post(
            f"{base_url}/assistant",
            json={"question": "What is the latest earthquake information in Atlantis?"},
            timeout=300.0,
        )
        degraded.raise_for_status()
        print(json.dumps({"case": "unsupported_geography", "body": degraded.json()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
