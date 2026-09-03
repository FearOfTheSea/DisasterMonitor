import json
from pathlib import Path

from disaster_monitor.application.services.drift_adaptation import (
    DriftObservation,
    load_drift_observations,
)
from disaster_monitor.application.services.offline_learning import (
    load_locked_trajectories,
)
from disaster_monitor.domain.learning import LearningPartition, LearningTrajectory

FIXTURES = Path(__file__).parent / "fixtures" / "continuous_learning"


def load_trajectories() -> tuple[str, tuple[LearningTrajectory, ...]]:
    payload = json.loads(
        (FIXTURES / "offline_trajectories.v1.json").read_text(encoding="utf-8")
    )
    if payload.get("fixture_version") != "dm-cl-a-v1":
        raise ValueError("Continuous-learning trajectory fixture version is invalid.")
    return load_locked_trajectories(payload)


def drift_inputs() -> tuple[
    str,
    tuple[DriftObservation, ...],
    tuple[LearningTrajectory, ...],
    tuple[LearningTrajectory, ...],
]:
    observation_payload = json.loads(
        (FIXTURES / "drift_observations.v1.json").read_text(encoding="utf-8")
    )
    if observation_payload.get("fixture_version") != "dm-cl-b-v1":
        raise ValueError("Continuous-learning drift fixture version is invalid.")
    dataset_version, observations = load_drift_observations(observation_payload)
    _, all_historical = load_trajectories()
    historical = tuple(
        item for item in all_historical if item.partition == LearningPartition.TEST
    )
    shifted_payload = json.loads(
        (FIXTURES / "shifted_trajectories.v1.json").read_text(encoding="utf-8")
    )
    if shifted_payload.get("fixture_version") != "dm-cl-b-shift-v1":
        raise ValueError("Continuous-learning shifted fixture version is invalid.")
    _, shifted = load_locked_trajectories(shifted_payload)
    return dataset_version, observations, historical, shifted
