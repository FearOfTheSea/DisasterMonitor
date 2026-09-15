"""Public MeteoAlarm country Atom/CAP warning adapter."""

import httpx

from disaster_monitor.infrastructure.disaster.http import SourcePayloadRecorder
from disaster_monitor.infrastructure.weather.atom_cap import AtomCapWarningAdapter

_FEED_ROOT = "https://feeds.meteoalarm.org/feeds"


class MeteoAlarmWarningAdapter(AtomCapWarningAdapter):
    geographic_scope = "Participating European national meteorological services"

    def __init__(
        self,
        *,
        countries: tuple[str, ...],
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10,
        maximum_response_bytes: int = 3_000_000,
        maximum_records: int = 500,
    ) -> None:
        normalized = tuple(
            dict.fromkeys(country.strip().casefold() for country in countries)
        )
        if not normalized or any(
            not country.isalpha() or len(country) > 60 for country in normalized
        ):
            raise ValueError("MeteoAlarm requires bounded country feed names.")
        super().__init__(
            feed_urls=tuple(
                f"{_FEED_ROOT}/meteoalarm-legacy-atom-{country}"
                for country in normalized
            ),
            source_id="meteoalarm-warnings",
            publisher="EUMETNET MeteoAlarm national warning services",
            attribution=(
                "Source: MeteoAlarm and the issuing national meteorological service."
            ),
            limitations=(
                "MeteoAlarm is a syndication layer for official European national "
                "warnings; always inspect the issuer and validity interval.",
                "Warning coverage and language vary by participating national service.",
                "A warning is not evidence that a physical incident or impact "
                "occurred.",
            ),
            profile="CAP 1.2 / MeteoAlarm Atom",
            allowed_hosts=frozenset({"feeds.meteoalarm.org"}),
            rights_id="meteoalarm-warnings",
            client=client,
            snapshot_recorder=snapshot_recorder,
            timeout_seconds=timeout_seconds,
            maximum_response_bytes=maximum_response_bytes,
            maximum_records=maximum_records,
        )
