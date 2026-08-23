"""Content-addressed filesystem blob storage for the local operational baseline."""

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


class FilesystemBlobStore:
    """Store immutable payloads under checksum-derived names."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, payload_sha256: str, content: bytes) -> str:
        destination = self._path(payload_sha256)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != content:
                raise RuntimeError("Content-addressed blob checksum collision.")
        else:
            destination.write_bytes(content)
        return destination.resolve().as_uri()

    def get(self, payload_sha256: str) -> bytes | None:
        source = self._path(payload_sha256)
        return source.read_bytes() if source.is_file() else None

    def delete(self, blob_uri: str) -> None:
        parsed = urlparse(blob_uri)
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            raise ValueError("Filesystem blob store can delete only file URIs.")
        raw_path = unquote(parsed.path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", raw_path):
            raw_path = raw_path[1:]
        candidate = Path(raw_path).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError("Blob deletion target escaped the configured root.")
        if candidate.is_file():
            candidate.unlink()

    def _path(self, payload_sha256: str) -> Path:
        digest = payload_sha256.removeprefix("sha256:")
        if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ValueError("Blob key must be a lowercase SHA-256 checksum.")
        return self._root / digest[:2] / digest[2:4] / f"{digest}.bin"
