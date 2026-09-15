"""Deterministic review-group suggestions for similar field reports."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt

from disaster_monitor.domain.field_reports import (
    FieldReportDuplicateCandidate,
    UnverifiedFieldReport,
)


class FieldReportDuplicateDetector:
    def __init__(
        self,
        *,
        maximum_time_delta: timedelta = timedelta(hours=6),
        maximum_distance_km: float = 10,
    ) -> None:
        if maximum_time_delta <= timedelta() or maximum_distance_km <= 0:
            raise ValueError("Duplicate-candidate bounds must be positive.")
        self._maximum_time_delta = maximum_time_delta
        self._maximum_distance_km = maximum_distance_km

    def detect(
        self, reports: tuple[UnverifiedFieldReport, ...]
    ) -> tuple[FieldReportDuplicateCandidate, ...]:
        candidates: list[FieldReportDuplicateCandidate] = []
        ordered = sorted(reports, key=lambda item: (item.captured_at, item.report_id))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                time_delta = abs(right.captured_at - left.captured_at)
                if time_delta > self._maximum_time_delta:
                    break
                distance = _distance_km(
                    left.geometry.centroid.longitude,
                    left.geometry.centroid.latitude,
                    right.geometry.centroid.longitude,
                    right.geometry.centroid.latitude,
                )
                same_type = left.report_type.casefold() == right.report_type.casefold()
                if distance > self._maximum_distance_km or not same_type:
                    continue
                first_report_id, second_report_id = sorted(
                    (left.report_id, right.report_id)
                )
                report_ids = (first_report_id, second_report_id)
                identity = sha256("|".join(report_ids).encode()).hexdigest()[:24]
                time_score = 1 - time_delta / self._maximum_time_delta
                distance_score = 1 - distance / self._maximum_distance_km
                candidates.append(
                    FieldReportDuplicateCandidate(
                        candidate_id=f"field-duplicate:{identity}",
                        report_ids=report_ids,
                        time_delta_seconds=time_delta.total_seconds(),
                        distance_km=distance,
                        same_type=True,
                        score=round((float(time_score) + distance_score + 1) / 3, 6),
                    )
                )
        return tuple(sorted(candidates, key=lambda item: item.candidate_id))


def _distance_km(
    left_longitude: float,
    left_latitude: float,
    right_longitude: float,
    right_latitude: float,
) -> float:
    latitude_delta = radians(right_latitude - left_latitude)
    longitude_delta = radians(right_longitude - left_longitude)
    value = (
        sin(latitude_delta / 2) ** 2
        + cos(radians(left_latitude))
        * cos(radians(right_latitude))
        * sin(longitude_delta / 2) ** 2
    )
    return 2 * 6_371.0088 * asin(sqrt(value))
