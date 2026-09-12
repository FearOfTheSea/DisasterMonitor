"""Stable selection identity shared by application and persistence adapters."""

from hashlib import sha256


def stable_selection_id(
    request_id: str,
    sensor: str,
    role: str,
    observation_key: str,
) -> str:
    """Return the provider-independent identity of one selected acquisition."""
    payload = "|".join((request_id, sensor, role, observation_key))
    return f"selection:{sha256(payload.encode()).hexdigest()[:24]}"


__all__ = ["stable_selection_id"]
