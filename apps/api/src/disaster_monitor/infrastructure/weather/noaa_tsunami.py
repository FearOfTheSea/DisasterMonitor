"""NOAA U.S. Tsunami Warning System CAP-TSU Atom adapter."""

import httpx

from disaster_monitor.infrastructure.disaster.http import SourcePayloadRecorder
from disaster_monitor.infrastructure.weather.atom_cap import AtomCapWarningAdapter


class NoaaTsunamiWarningAdapter(AtomCapWarningAdapter):
    geographic_scope = "NOAA U.S. Tsunami Warning System areas of responsibility"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10,
        maximum_response_bytes: int = 3_000_000,
        maximum_records: int = 500,
    ) -> None:
        super().__init__(
            feed_urls=(
                "https://www.tsunami.gov/events/xml/PAAQAtom.xml",
                "https://www.tsunami.gov/events/xml/PHEBAtom.xml",
            ),
            source_id="noaa-tsunami-warnings",
            publisher="NOAA U.S. Tsunami Warning System",
            attribution="Source: NOAA U.S. Tsunami Warning System.",
            limitations=(
                "CAP-TSU messages are official warning artifacts, not physical "
                "tsunami observations.",
                "Geographic responsibility and message availability are limited to "
                "the U.S. Tsunami Warning System products.",
                "A present XML signature is retained as metadata but is not reported "
                "as verified unless cryptographic verification succeeds.",
            ),
            profile="CAP-TSU",
            allowed_hosts=frozenset({"www.tsunami.gov", "tsunami.gov"}),
            rights_id="noaa-tsunami-warnings",
            client=client,
            snapshot_recorder=snapshot_recorder,
            timeout_seconds=timeout_seconds,
            maximum_response_bytes=maximum_response_bytes,
            maximum_records=maximum_records,
        )
