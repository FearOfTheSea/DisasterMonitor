"""Domain values for event-focused ground imagery.

The imagery feature deliberately keeps source geometry, event geography, and
observation metadata separate from provider clients.  The package contains no
filesystem, HTTP, database, or geospatial-library dependencies.
"""

from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    ImpactOnset,
    Observation,
    ObservationQuality,
    ObservationReadiness,
    OnsetPrecision,
    Sensor,
    TemporalRole,
    radar_comparison_compatibility,
)
from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    Coordinate,
    ImageryRegionVersion,
    MultiPolygon,
    Polygon,
    RegionEvidence,
    RegionRole,
    RegionSource,
    RegionSourceKind,
)

__all__ = [
    "AcquisitionIdentity",
    "AssociationStatus",
    "CaptureInterval",
    "Coordinate",
    "ImpactOnset",
    "ImageryRegionVersion",
    "MultiPolygon",
    "Observation",
    "ObservationQuality",
    "ObservationReadiness",
    "OnsetPrecision",
    "Polygon",
    "RegionEvidence",
    "RegionRole",
    "RegionSource",
    "RegionSourceKind",
    "Sensor",
    "TemporalRole",
    "radar_comparison_compatibility",
]
