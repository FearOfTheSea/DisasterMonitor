"""Typed distribution-drift detection and non-authority safe adaptation."""

from collections.abc import Mapping
from hashlib import sha256

from disaster_monitor.application.services.offline_learning import (
    APPROVED_ANALYTICAL_TUNING_V1,
    DRIFT_ADAPTED_ANALYTICAL_TUNING_V2,
    evaluate_parameters,
)
from disaster_monitor.domain.learning import (
    DriftAdaptationRelease,
    DriftAdaptationStatus,
    DriftAssessment,
    DriftObservation,
    DriftType,
    LearningTrajectory,
)


class DistributionDriftDetector:
    """Detect declared metadata shifts without changing trust or policy."""

    def __init__(
        self,
        *,
        latency_ratio_threshold: float = 2.0,
        image_distance_threshold: float = 0.30,
    ) -> None:
        if latency_ratio_threshold <= 1 or not 0 < image_distance_threshold <= 1:
            raise ValueError("Drift detector thresholds are invalid.")
        self._latency_ratio_threshold = latency_ratio_threshold
        self._image_distance_threshold = image_distance_threshold

    def assess(self, observation: DriftObservation) -> DriftAssessment:
        signals: list[str] = []
        if observation.unknown_hazard:
            signals.append("drift.unknown_hazard")
        if observation.unknown_language:
            signals.append("drift.unknown_language")
        if observation.unknown_provider_schema:
            signals.append("drift.unknown_provider_schema")
        if observation.source_latency_ratio > self._latency_ratio_threshold:
            signals.append("drift.source_latency")
        if observation.image_domain_distance > self._image_distance_threshold:
            signals.append("drift.image_domain")
        return DriftAssessment(
            observation_id=observation.observation_id,
            drift_type=observation.drift_type,
            detected=bool(signals),
            severe=observation.severity >= 0.80,
            signal_ids=tuple(signals),
            provenance_ids=observation.provenance_ids,
        )


class DriftAdaptationController:
    """Approve bounded focus weights or retain the prior non-adaptive policy."""

    def __init__(self, detector: DistributionDriftDetector | None = None) -> None:
        self._detector = detector or DistributionDriftDetector()

    def evaluate(
        self,
        dataset_version: str,
        observations: tuple[DriftObservation, ...],
        *,
        historical_trajectories: tuple[LearningTrajectory, ...],
        shifted_trajectories: tuple[LearningTrajectory, ...],
    ) -> DriftAdaptationRelease:
        if not observations:
            raise ValueError("Drift adaptation requires observations.")
        assessments = tuple(self._detector.assess(item) for item in observations)
        seeded = tuple(item for item in observations if item.expected_drift)
        detected_seeded = sum(
            assessment.detected
            for observation, assessment in zip(observations, assessments, strict=True)
            if observation.expected_drift
        )
        drift_recall = detected_seeded / len(seeded) if seeded else 1.0
        shifted_baseline = evaluate_parameters(
            APPROVED_ANALYTICAL_TUNING_V1, shifted_trajectories
        )
        shifted_candidate = evaluate_parameters(
            DRIFT_ADAPTED_ANALYTICAL_TUNING_V2, shifted_trajectories
        )
        historical_baseline = evaluate_parameters(
            APPROVED_ANALYTICAL_TUNING_V1, historical_trajectories
        )
        historical_candidate = evaluate_parameters(
            DRIFT_ADAPTED_ANALYTICAL_TUNING_V2, historical_trajectories
        )
        severe_undetected = any(
            observation.expected_drift
            and assessment.severe
            and not assessment.detected
            and observation.unsupported_claim_if_undetected
            for observation, assessment in zip(observations, assessments, strict=True)
        )
        historical_degradation = (
            historical_baseline.task_accuracy - historical_candidate.task_accuracy
        )
        grounding_regression = (
            historical_baseline.grounding_rate - historical_candidate.grounding_rate
        )
        safety_regression = (
            historical_candidate.critical_safety_rate
            < historical_baseline.critical_safety_rate
        )
        if severe_undetected:
            safe_mode_reason = "severe_undetected_shift"
        elif drift_recall < 0.90:
            safe_mode_reason = "drift_recall_below_gate"
        elif shifted_candidate.task_accuracy <= shifted_baseline.task_accuracy:
            safe_mode_reason = "no_shifted_set_improvement"
        elif historical_degradation > 0.01:
            safe_mode_reason = "historical_task_degradation"
        elif grounding_regression > 0.01:
            safe_mode_reason = "historical_grounding_degradation"
        elif safety_regression:
            safe_mode_reason = "critical_safety_regression"
        else:
            safe_mode_reason = None
        status = (
            DriftAdaptationStatus.ADAPTED
            if safe_mode_reason is None
            else DriftAdaptationStatus.NON_ADAPTIVE_SAFE_MODE
        )
        approved = (
            DRIFT_ADAPTED_ANALYTICAL_TUNING_V2
            if status == DriftAdaptationStatus.ADAPTED
            else APPROVED_ANALYTICAL_TUNING_V1
        )
        provenance_ids = tuple(
            dict.fromkeys(
                (
                    *(
                        value
                        for observation in observations
                        for value in observation.provenance_ids
                    ),
                    *(
                        value
                        for trajectory in historical_trajectories
                        for value in trajectory.provenance_ids
                    ),
                    *(
                        value
                        for trajectory in shifted_trajectories
                        for value in trajectory.provenance_ids
                    ),
                )
            )
        )
        material = "|".join(
            (
                dataset_version,
                status.value,
                approved.parameter_set_id,
                *(item.observation_id for item in observations),
            )
        )
        return DriftAdaptationRelease(
            release_id=(
                f"drift-adaptation:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            dataset_version=dataset_version,
            status=status,
            prior_parameters=APPROVED_ANALYTICAL_TUNING_V1,
            candidate_parameters=DRIFT_ADAPTED_ANALYTICAL_TUNING_V2,
            approved_parameters=approved,
            assessments=assessments,
            drift_recall=drift_recall,
            shifted_baseline_evaluation=shifted_baseline,
            shifted_candidate_evaluation=shifted_candidate,
            historical_baseline_evaluation=historical_baseline,
            historical_candidate_evaluation=historical_candidate,
            safe_mode_reason=safe_mode_reason,
            provenance_ids=provenance_ids,
        )


def load_drift_observations(
    payload: Mapping[str, object],
) -> tuple[str, tuple[DriftObservation, ...]]:
    if set(payload) != {"fixture_version", "dataset_version", "observations"}:
        raise ValueError("Drift fixture schema is invalid.")
    dataset_version = _string(payload["dataset_version"], "dataset_version")
    raw = payload["observations"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("Drift fixture requires observations.")
    observations: list[DriftObservation] = []
    expected = {
        "id",
        "drift_type",
        "expected_drift",
        "severity",
        "unknown_hazard",
        "unknown_language",
        "unknown_provider_schema",
        "source_latency_ratio",
        "image_domain_distance",
        "unsupported_claim_if_undetected",
        "provenance_ids",
    }
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != expected:
            raise ValueError("Drift observation schema is invalid.")
        provenance = item["provenance_ids"]
        if (
            not isinstance(provenance, list)
            or not provenance
            or not all(isinstance(value, str) and value.strip() for value in provenance)
        ):
            raise ValueError("Drift observation provenance is invalid.")
        observations.append(
            DriftObservation(
                observation_id=_string(item["id"], "id"),
                drift_type=DriftType(_string(item["drift_type"], "drift_type")),
                expected_drift=item["expected_drift"] is True,
                severity=float(item["severity"]),
                unknown_hazard=item["unknown_hazard"] is True,
                unknown_language=item["unknown_language"] is True,
                unknown_provider_schema=item["unknown_provider_schema"] is True,
                source_latency_ratio=float(item["source_latency_ratio"]),
                image_domain_distance=float(item["image_domain_distance"]),
                unsupported_claim_if_undetected=(
                    item["unsupported_claim_if_undetected"] is True
                ),
                provenance_ids=tuple(str(value).strip() for value in provenance),
            )
        )
    return dataset_version, tuple(observations)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"Drift {field} must be a bounded string.")
    return value.strip()
