"""Presentation-safe failures for the Ground view application boundary."""


class GroundImageryError(Exception):
    """Base class for presentation-safe imagery workflow failures."""


class GroundImageryRequestNotFound(GroundImageryError):
    """The requested imagery workflow is outside the available scope."""


class GroundImageryArtifactNotFound(GroundImageryError):
    """The requested immutable imagery artifact is outside the available scope."""


class GroundImageryIncidentNotFound(GroundImageryError):
    """The incident cannot be resolved through the read-only incident port."""


__all__ = [
    "GroundImageryArtifactNotFound",
    "GroundImageryError",
    "GroundImageryIncidentNotFound",
    "GroundImageryRequestNotFound",
]
