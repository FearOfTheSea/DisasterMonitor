from datetime import UTC, datetime
from pathlib import Path

from disaster_monitor.infrastructure.weather.cap_parser import parse_cap_alert


def test_cap_parser_preserves_profile_multilingual_geometry_and_signature() -> None:
    payload = (
        Path(__file__).parents[1] / "fixtures" / "cap_multilingual_update.xml"
    ).read_bytes()

    alert = parse_cap_alert(
        payload,
        source_id="meteoalarm-warnings",
        publisher="MeteoAlarm",
        canonical_url="https://feeds.meteoalarm.org/fixture.xml",
        retrieved_at=datetime(2026, 9, 14, 5, 5, tzinfo=UTC),
        attribution="MeteoAlarm warnings, CC BY 4.0.",
        limitations=("Warning evidence is not incident confirmation.",),
        profile="CAP-1.2",
    )

    assert alert.identifier == "2.49.0.1.250.0.fixture"
    assert alert.message_type.value == "update"
    assert alert.references[0].identifier == "2.49.0.1.250.0.previous"
    assert [info.language for info in alert.infos] == ["en-GB", "vi"]
    assert alert.infos[0].event_codes == (("profile:event", "FL"),)
    assert alert.infos[0].areas[0].geocodes == (("EMMA_ID", "VI001"),)
    coordinate = alert.infos[0].areas[0].polygons[0].polygons[0].exterior.coordinates[0]
    assert (coordinate.latitude, coordinate.longitude) == (10.0, 106.0)
    assert alert.signature_present is True
    assert alert.signature_verified is None


def test_cap_parser_preserves_source_point_encoded_as_zero_radius_circle() -> None:
    payload = (
        Path(__file__).parents[1] / "fixtures" / "cap_multilingual_update.xml"
    ).read_text()
    payload = payload.replace(
        "</area>", "<circle>10.5,106.5 0.0</circle></area>", 1
    ).encode()

    alert = parse_cap_alert(
        payload,
        source_id="noaa-tsunami-warnings",
        publisher="NOAA",
        canonical_url="https://www.tsunami.gov/fixture.xml",
        retrieved_at=datetime(2026, 9, 15, tzinfo=UTC),
        attribution="NOAA warning.",
        limitations=("Warning evidence is not incident confirmation.",),
        profile="CAP-TSU",
    )

    assert alert.infos[0].areas[0].circles[0].radius_km == 0
