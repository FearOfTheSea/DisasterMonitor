"""Deterministic local triage over operator-labelled signal examples."""

from __future__ import annotations

import re
from collections import defaultdict

from disaster_monitor.domain.social_signals import (
    OperatorSignalLabel,
    SignalCategory,
    SignalClassification,
    UntrustedSocialSignal,
)

_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)


class LocalSignalTriageClassifier:
    def __init__(self, *, model_id: str, model_version: str) -> None:
        if not model_id.strip() or not model_version.strip():
            raise ValueError("Local signal classifiers require versioned identity.")
        self._model_id = model_id
        self._model_version = model_version

    def classify(
        self,
        signal: UntrustedSocialSignal,
        examples: tuple[OperatorSignalLabel, ...],
    ) -> SignalClassification:
        if not examples:
            raise ValueError("Classification requires operator-labelled examples.")
        candidate_tokens = _tokens(signal.text)
        category_scores: dict[SignalCategory, float] = defaultdict(float)
        for example in examples:
            example_tokens = _tokens(example.signal_text)
            union = candidate_tokens | example_tokens
            similarity = (
                len(candidate_tokens & example_tokens) / len(union) if union else 0.0
            )
            category_scores[example.category] = max(
                category_scores[example.category], similarity
            )
        category = max(
            SignalCategory,
            key=lambda item: (category_scores[item], item.value),
        )
        return SignalClassification(
            signal_id=signal.signal_id,
            category=category,
            relevance_score=category_scores[category],
            model_id=self._model_id,
            model_version=self._model_version,
            training_label_ids=tuple(item.label_id for item in examples),
        )


def _tokens(text: str) -> frozenset[str]:
    return frozenset(match.group().casefold() for match in _TOKEN.finditer(text))


__all__ = ["LocalSignalTriageClassifier"]
