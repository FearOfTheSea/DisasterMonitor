"""Provider-neutral timestamp normalization at the adapter boundary."""

from datetime import UTC, datetime


def normalize_timestamp(value: object) -> datetime | None:
    """Normalize datetime, Unix timestamp, and ISO-8601 provider values."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 100_000_000_000:
            number /= 1_000
        return datetime.fromtimestamp(number, tz=UTC)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
