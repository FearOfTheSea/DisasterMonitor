"""Application-facing trusted operator identity configuration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrustedOperatorIdentityPolicy:
    """Describe the trusted identity boundary exposed to HTTP presentation."""

    enabled: bool
    header_name: str
