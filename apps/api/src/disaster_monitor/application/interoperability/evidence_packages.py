"""Deterministic bounded evidence-package export and offline verification."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

_SCHEMA_VERSION = "disastermonitor-evidence-package.v1"
_REQUIRED_FILES = {
    "incident.json",
    "normalized-data.json",
    "findings.json",
    "imagery-manifests.json",
    "source-links.json",
}


class EvidencePackageVerificationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedEvidencePackage:
    incident_id: str
    created_at: datetime
    software_version: str
    policy_versions: tuple[str, ...]
    verified_files: tuple[str, ...]
    external: bool = True
    historical: bool = True
    merge_into_live_state: bool = False


class EvidencePackageBuilder:
    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._clock = clock

    def build(
        self,
        *,
        incident_id: str,
        incident_snapshot: dict[str, Any],
        source_links: tuple[str, ...],
        normalized_data: dict[str, Any],
        findings: tuple[dict[str, Any], ...],
        imagery_manifests: tuple[dict[str, Any], ...],
        software_version: str,
        policy_versions: tuple[str, ...],
    ) -> bytes:
        if not incident_id.strip() or not software_version.strip():
            raise ValueError(
                "Evidence packages require incident and software identity."
            )
        if any(not url.startswith("https://") for url in source_links):
            raise ValueError("Evidence package source links must use HTTPS.")
        created_at = self._clock()
        files = {
            "incident.json": _json_bytes(incident_snapshot),
            "normalized-data.json": _json_bytes(normalized_data),
            "findings.json": _json_bytes(list(findings)),
            "imagery-manifests.json": _json_bytes(list(imagery_manifests)),
            "source-links.json": _json_bytes(list(source_links)),
        }
        manifest = {
            "schema_version": _SCHEMA_VERSION,
            "classification": "bounded_incident_snapshot",
            "incident_id": incident_id,
            "created_at": created_at.isoformat(),
            "software_version": software_version,
            "policy_versions": list(policy_versions),
            "files": [
                {
                    "path": name,
                    "sha256": sha256(content).hexdigest(),
                    "bytes": len(content),
                }
                for name, content in sorted(files.items())
            ],
            "import_policy": {
                "external": True,
                "historical": True,
                "merge_into_live_state": False,
            },
        }
        output = BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            _write(archive, "manifest.json", _json_bytes(manifest))
            for name, content in sorted(files.items()):
                _write(archive, name, content)
        return output.getvalue()


class EvidencePackageVerifier:
    def __init__(self, *, maximum_bytes: int = 50_000_000) -> None:
        self._maximum_bytes = maximum_bytes

    def verify(self, content: bytes) -> VerifiedEvidencePackage:
        if not content or len(content) > self._maximum_bytes:
            raise EvidencePackageVerificationError(
                "Evidence package is empty or exceeds the byte limit."
            )
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = archive.namelist()
                if (
                    len(names) > 10_000
                    or sum(info.file_size for info in archive.infolist())
                    > self._maximum_bytes
                ):
                    raise EvidencePackageVerificationError(
                        "Evidence package expanded content exceeds the byte limit."
                    )
                if len(names) != len(set(names)) or any(
                    _unsafe_path(name) for name in names
                ):
                    raise EvidencePackageVerificationError(
                        "Evidence package contains unsafe or duplicate paths."
                    )
                if "manifest.json" not in names:
                    raise EvidencePackageVerificationError(
                        "Evidence package manifest is missing."
                    )
                manifest = json.loads(archive.read("manifest.json"))
                return self._verify_manifest(archive, manifest)
        except EvidencePackageVerificationError:
            raise
        except (
            BadZipFile,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as error:
            raise EvidencePackageVerificationError(
                "Evidence package schema is invalid."
            ) from error

    @staticmethod
    def _verify_manifest(archive: ZipFile, manifest: object) -> VerifiedEvidencePackage:
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != _SCHEMA_VERSION
        ):
            raise EvidencePackageVerificationError(
                "Evidence package schema version is unsupported."
            )
        raw_files = manifest.get("files")
        if not isinstance(raw_files, list):
            raise EvidencePackageVerificationError(
                "Evidence package file manifest is invalid."
            )
        declared: set[str] = set()
        for item in raw_files:
            if not isinstance(item, dict):
                raise EvidencePackageVerificationError(
                    "Evidence package file manifest is invalid."
                )
            path = str(item.get("path") or "")
            expected = str(item.get("sha256") or "")
            if path in declared or path not in archive.namelist():
                raise EvidencePackageVerificationError(
                    "Evidence package declared files are incomplete."
                )
            file_content = archive.read(path)
            if (
                len(file_content) != item.get("bytes")
                or sha256(file_content).hexdigest() != expected
            ):
                raise EvidencePackageVerificationError(
                    f"Evidence package checksum failed for {path}."
                )
            declared.add(path)
        if not _REQUIRED_FILES.issubset(declared):
            raise EvidencePackageVerificationError(
                "Evidence package required files are missing."
            )
        if set(archive.namelist()) != declared | {"manifest.json"}:
            raise EvidencePackageVerificationError(
                "Evidence package contains undeclared files."
            )
        policy = manifest.get("import_policy")
        if not isinstance(policy, dict) or policy != {
            "external": True,
            "historical": True,
            "merge_into_live_state": False,
        }:
            raise EvidencePackageVerificationError(
                "Evidence package import boundary is invalid."
            )
        created_at = datetime.fromisoformat(str(manifest["created_at"]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise EvidencePackageVerificationError(
                "Evidence package creation time lacks a timezone."
            )
        return VerifiedEvidencePackage(
            incident_id=str(manifest["incident_id"]),
            created_at=created_at,
            software_version=str(manifest["software_version"]),
            policy_versions=tuple(str(item) for item in manifest["policy_versions"]),
            verified_files=tuple(sorted(declared)),
        )


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _write(archive: ZipFile, name: str, content: bytes) -> None:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    archive.writestr(info, content, compresslevel=9)


def _unsafe_path(name: str) -> bool:
    return not name or name.startswith(("/", "\\")) or ".." in name.split("/")
