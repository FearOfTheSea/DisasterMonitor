"""Metric helpers for the frozen Evidence / World-State release gates."""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from typing import Any


@dataclass(frozen=True, slots=True)
class EventIdentityMetrics:
    assignment_correct: int = 0
    assignment_total: int = 0
    ambiguity_correct: int = 0
    ambiguity_total: int = 0
    prohibited_conflations: int = 0
    cross_scope_merges: int = 0

    @property
    def assignment_rate(self) -> float:
        return self.assignment_correct / self.assignment_total

    @property
    def ambiguity_rate(self) -> float:
        return self.ambiguity_correct / self.ambiguity_total


def score_partition(
    expected_groups: tuple[frozenset[str], ...],
    predicted_groups: tuple[frozenset[str], ...],
) -> tuple[int, int, int]:
    """Score pairwise physical-event assignment and false-positive merges."""
    observations = sorted(set().union(*expected_groups))
    expected_by_item = {
        item: index for index, group in enumerate(expected_groups) for item in group
    }
    predicted_by_item = {
        item: index for index, group in enumerate(predicted_groups) for item in group
    }
    correct = 0
    prohibited_conflations = 0
    for first, second in combinations(observations, 2):
        expected_same = expected_by_item[first] == expected_by_item[second]
        predicted_same = predicted_by_item[first] == predicted_by_item[second]
        correct += expected_same == predicted_same
        prohibited_conflations += predicted_same and not expected_same
    return correct, len(tuple(combinations(observations, 2))), prohibited_conflations


def score_labels(
    expected: Mapping[str, str], predicted: Mapping[str, str]
) -> dict[str, tuple[int, int]]:
    """Return per-class correct/total counts; missing predictions are failures."""
    counts: dict[str, tuple[int, int]] = {}
    for key, expected_label in expected.items():
        passed, total = counts.get(expected_label, (0, 0))
        counts[expected_label] = (
            passed + (predicted.get(key) == expected_label),
            total + 1,
        )
    return counts


def merge_counts(
    target: dict[str, tuple[int, int]], source: Mapping[str, tuple[int, int]]
) -> None:
    for key, (passed, total) in source.items():
        old_passed, old_total = target.get(key, (0, 0))
        target[key] = (old_passed + passed, old_total + total)


def metric_rate(counts: tuple[int, int]) -> float:
    passed, total = counts
    return passed / total if total else 1.0


def brier_score(predictions: list[float], outcomes: list[int]) -> float:
    """Return mean squared probabilistic error for binary outcomes."""
    if not predictions or len(predictions) != len(outcomes):
        raise ValueError("Brier score requires equal non-empty inputs.")
    return sum(
        (prediction - outcome) ** 2
        for prediction, outcome in zip(predictions, outcomes, strict=True)
    ) / len(predictions)


def expected_calibration_error(
    predictions: list[float], outcomes: list[int], *, bins: int
) -> float:
    """Compute equal-width-bin ECE weighted by each bin's sample fraction."""
    if not predictions or len(predictions) != len(outcomes) or bins <= 0:
        raise ValueError("ECE requires equal non-empty inputs and positive bins.")
    buckets: list[list[tuple[float, int]]] = [[] for _index in range(bins)]
    for prediction, outcome in zip(predictions, outcomes, strict=True):
        index = min(int(prediction * bins), bins - 1)
        buckets[index].append((prediction, outcome))
    total = len(predictions)
    error = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        confidence = sum(item[0] for item in bucket) / len(bucket)
        accuracy = sum(item[1] for item in bucket) / len(bucket)
        error += len(bucket) / total * abs(accuracy - confidence)
    return error


def hypothesis_separation_rate(
    hypotheses: list[Any], observed_products: list[Any]
) -> float:
    """Measure inferred typing and absence from the verified-observation product."""
    if not hypotheses:
        return 1.0
    passed = sum(
        getattr(item, "truth_status", None) == "inferred"
        and item not in observed_products
        for item in hypotheses
    )
    return passed / len(hypotheses)
