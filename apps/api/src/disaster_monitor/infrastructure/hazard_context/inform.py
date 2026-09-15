"""Local versioned INFORM Risk baseline-vulnerability dataset adapter."""

import csv
from pathlib import Path

from disaster_monitor.domain.hazard_context import BaselineVulnerabilityContext


class InformRiskDataset:
    def __init__(self, path: Path, *, version: str) -> None:
        if not path.is_file() or not version.strip():
            raise ValueError("INFORM adapter requires a local dataset and version.")
        self._path = path
        self._version = version

    def lookup(self, place_code: str) -> BaselineVulnerabilityContext | None:
        with self._path.open(encoding="utf-8", newline="") as source:
            matches = [
                row
                for row in csv.DictReader(source)
                if row.get("iso3", "").strip().upper() == place_code.strip().upper()
            ]
        if len(matches) > 1:
            raise ValueError("INFORM dataset contains duplicate place identities.")
        if not matches:
            return None
        row = matches[0]
        return BaselineVulnerabilityContext(
            place_code=place_code.strip().upper(),
            place_name=row["place_name"].strip(),
            aggregation_level=row["aggregation_level"].strip(),
            dataset_version=self._version,
            vintage=int(row["vintage"]),
            risk_index=float(row["risk"]),
            vulnerability_index=float(row["vulnerability"]),
            coping_capacity_index=float(row["coping_capacity"]),
            source_id="inform-risk",
            context_role="baseline_vulnerability",
            interpretation=(
                "Slow-changing baseline vulnerability and coping-capacity context; "
                "this is not event impact or evidence that anyone was affected."
            ),
        )
