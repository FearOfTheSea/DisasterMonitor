"""Typed baseline vulnerability context."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BaselineVulnerabilityContext:
    place_code: str
    place_name: str
    aggregation_level: str
    dataset_version: str
    vintage: int
    risk_index: float
    vulnerability_index: float
    coping_capacity_index: float
    source_id: str
    context_role: str
    interpretation: str

    def __post_init__(self) -> None:
        if self.context_role != "baseline_vulnerability":
            raise ValueError("INFORM context must remain baseline vulnerability.")
        if not 1900 <= self.vintage <= 2200:
            raise ValueError("INFORM vintage is outside its bounds.")
