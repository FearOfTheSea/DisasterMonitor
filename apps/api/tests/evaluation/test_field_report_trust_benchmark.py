import json
from pathlib import Path

import pytest

from disaster_monitor.evaluation.field_report_trust import (
    REQUIRED_FIELD_REPORT_TRUST_CATEGORIES,
    FieldReportTrustBenchmarkError,
    run_field_report_trust_benchmark,
)

REPOSITORY_ROOT = Path(__file__).parents[4]
BENCHMARK_PATH = REPOSITORY_ROOT / "evaluation" / "field_report_trust_benchmark.v1.json"


def test_field_report_trust_benchmark_covers_p3_failures_and_passes() -> None:
    first = run_field_report_trust_benchmark(BENCHMARK_PATH)
    second = run_field_report_trust_benchmark(BENCHMARK_PATH)

    assert first == second
    assert set(first.categories) == REQUIRED_FIELD_REPORT_TRUST_CATEGORIES
    assert first.authority_violations == 0
    assert first.official_evidence_override_count == 0
    assert first.auto_merge_count == 0
    assert first.exact_location_inventions == 0
    assert first.manual_review_rate == 1
    assert first.sensitive_content_rejections == 1
    assert first.duplicate_candidate_count == 19_900
    assert first.promotion_eligible is True
    assert "does not classify" in first.scope_note


def test_field_report_trust_benchmark_rejects_missing_safety_category(
    tmp_path: Path,
) -> None:
    document = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    document["cases"] = document["cases"][:-1]
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FieldReportTrustBenchmarkError, match="missing categories"):
        run_field_report_trust_benchmark(incomplete)
