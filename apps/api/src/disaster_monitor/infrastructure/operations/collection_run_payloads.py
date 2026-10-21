"""Versioned, lossless discovery projections; acquisition evidence stays separate."""

import zlib
from dataclasses import dataclass

from pydantic import TypeAdapter

from disaster_monitor.application.ports.discovery import DiscoveryCapacityError
from disaster_monitor.domain.discovery import DiscoveryRun

_RUN = TypeAdapter(DiscoveryRun)
_HEADER = b"DMRUN-ZLIB-1:"
_COMPRESSION_THRESHOLD = 64 * 1024


@dataclass(frozen=True, slots=True)
class DiscoveryRunPayloads:
    maximum_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.maximum_bytes < 1:
            raise ValueError("Discovery projection limit must be positive.")

    def encode(self, run: DiscoveryRun) -> bytes:
        raw = _RUN.dump_json(run)
        if len(raw) > self.maximum_bytes:
            raise DiscoveryCapacityError()
        if len(raw) < _COMPRESSION_THRESHOLD:
            return raw
        compressed = _HEADER + zlib.compress(raw, level=1)
        return compressed if len(compressed) < len(raw) else raw

    def decode(self, payload: str | bytes) -> DiscoveryRun:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        if raw.startswith(_HEADER):
            inflater = zlib.decompressobj()
            try:
                expanded = inflater.decompress(
                    raw[len(_HEADER) :], self.maximum_bytes + 1
                )
            except zlib.error as error:
                raise ValueError("Retained discovery projection is corrupt.") from error
            if len(expanded) > self.maximum_bytes:
                raise ValueError("Retained discovery projection exceeds decode limit.")
            if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                raise ValueError(
                    "Retained discovery projection is incomplete or corrupt."
                )
            raw = expanded
        elif raw.startswith(b"DMRUN-"):
            raise ValueError("Unsupported discovery projection encoding.")
        # Plain JSON is also a current encoding for small runs. Preserve access
        # to older large JSON records independently of new-write/decode limits.
        return _RUN.validate_json(raw)
