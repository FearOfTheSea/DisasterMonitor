import pytest

from disaster_monitor.domain.hazards.intensity import IntensityScale, parse_intensity


@pytest.mark.parametrize(
    ("value", "scale", "level"),
    [
        ("MMI 6+", IntensityScale.MODIFIED_MERCALLI, 6.0),
        ("MMI 6-", IntensityScale.MODIFIED_MERCALLI, 5.5),
        ("JMA ６+", IntensityScale.JMA, 6.0),
        ("5-", IntensityScale.JMA, 4.5),
        (6.5, IntensityScale.UNSPECIFIED, 6.5),
    ],
)
def test_intensity_retains_declared_scale(value, scale, level) -> None:
    reading = parse_intensity(value)
    assert reading is not None
    assert reading.scale is scale
    assert reading.level == level


@pytest.mark.parametrize(
    "value",
    [None, True, float("nan"), float("inf"), "MMI 17", "MMI 6 text", "estimated 7", ""],
)
def test_unknown_or_malformed_intensity_is_not_evidence(value) -> None:
    assert parse_intensity(value) is None
