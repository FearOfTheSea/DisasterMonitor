"""Run the full MM-A/MM-B/MM-C automated release gate with a real local VLM."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from disaster_monitor.evaluation.multimodal_release import (
    MultimodalReleaseError,
    evaluate_locked_release,
)
from disaster_monitor.infrastructure.vision.ollama_vision_adapter import (
    OllamaVisionAdapter,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged-root", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="qwen3-vl:2b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    arguments = parser.parse_args()
    root = arguments.staged_root.resolve()
    manifest = (arguments.manifest or root / "locked-release-manifest.json").resolve()
    specification = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "evaluation"
        / "fixtures"
        / "multimodal"
        / "benchmark_spec.v1.json"
    )

    try:
        result = asyncio.run(
            _evaluate(
                root=root,
                manifest=manifest,
                specification=specification,
                model=arguments.model,
                ollama_url=arguments.ollama_url,
            )
        )
    except (MultimodalReleaseError, OSError, ValueError) as error:
        payload = {
            "status": "blocked_or_failed",
            "passed": False,
            "error": str(error),
            "manifest": str(manifest),
            "model": arguments.model,
        }
        _emit(payload, arguments.output)
        print(f"MM full release evaluation failed closed: {error}")
        return 2

    payload = asdict(result)
    payload["status"] = "passed" if result.passed else "failed"
    _emit(payload, arguments.output)
    metrics = result.metrics
    print(
        "MM full release: "
        f"damage macro-F1={metrics['damage']['macro_f1']:.3f}; "
        f"VQA factual={metrics['vqa']['factual_accuracy']:.3f}; "
        f"association={metrics['association']['association_accuracy']:.3f}; "
        f"map attribution={metrics['map']['attribution_accuracy']:.3f}; "
        f"capability={'PASS' if result.capability_passed else 'FAIL'}; "
        f"safety={'PASS' if result.safety_passed else 'FAIL'}"
    )
    return 0 if result.passed else 1


async def _evaluate(
    *, root: Path, manifest: Path, specification: Path, model: str, ollama_url: str
):
    adapter = OllamaVisionAdapter(model, ollama_url)
    try:
        return await evaluate_locked_release(
            staged_root=root,
            manifest_path=manifest,
            specification_path=specification,
            analyzer=adapter,
        )
    finally:
        await adapter.aclose()


def _emit(payload: dict, output: Path | None) -> None:
    encoded = json.dumps(payload, indent=2) + "\n"
    if output is None:
        print(encoded, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    print(f"Machine-readable MM result: {output.resolve()}")


if __name__ == "__main__":
    raise SystemExit(main())
