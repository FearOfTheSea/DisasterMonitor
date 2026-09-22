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
        snapshot_ids = tuple(
            value
            for key in ("event_id", "incident_id")
            if isinstance((value := incident_snapshot.get(key)), str) and value.strip()
        )
        if snapshot_ids and any(value != incident_id for value in snapshot_ids):
            raise ValueError("Evidence package incident identity is inconsistent.")
        if any(not value.strip() for value in policy_versions):
            raise ValueError("Evidence package policy versions must not be empty.")
        if any(not isinstance(item, dict) for item in (*findings, *imagery_manifests)):
            raise ValueError("Evidence package records must be JSON objects.")
        if any(not url.startswith("https://") for url in source_links):
            raise ValueError("Evidence package source links must use HTTPS.")
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Evidence package creation time must be timezone-aware.")
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
        if maximum_bytes <= 0:
            raise ValueError("Evidence-package byte limits must be positive.")
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
            or manifest.get("classification") != "bounded_incident_snapshot"
        ):
            raise EvidencePackageVerificationError(
                "Evidence package schema version is unsupported."
            )
        incident_id = _required_manifest_text(manifest, "incident_id")
        software_version = _required_manifest_text(manifest, "software_version")
        raw_policy_versions = manifest.get("policy_versions")
        if not isinstance(raw_policy_versions, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in raw_policy_versions
        ):
            raise EvidencePackageVerificationError(
                "Evidence package policy versions are invalid."
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
            expected = item.get("sha256")
            expected_bytes = item.get("bytes")
            if (
                path == "manifest.json"
                or _unsafe_path(path)
                or path in declared
                or path not in archive.namelist()
            ):
                raise EvidencePackageVerificationError(
                    "Evidence package declared files are incomplete."
                )
            if (
                not isinstance(expected, str)
                or len(expected) != 64
                or any(character not in "0123456789abcdef" for character in expected)
                or isinstance(expected_bytes, bool)
                or not isinstance(expected_bytes, int)
                or expected_bytes < 0
            ):
                raise EvidencePackageVerificationError(
                    "Evidence package file metadata is invalid."
                )
            file_content = archive.read(path)
            if (
                len(file_content) != expected_bytes
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
        _validate_payload_documents(archive, incident_id=incident_id)
        created_at = datetime.fromisoformat(str(manifest["created_at"]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise EvidencePackageVerificationError(
                "Evidence package creation time lacks a timezone."
            )
        return VerifiedEvidencePackage(
            incident_id=incident_id,
            created_at=created_at,
            software_version=software_version,
            policy_versions=tuple(raw_policy_versions),
            verified_files=tuple(sorted(declared)),
        )


def _required_manifest_text(manifest: dict[str, Any], key: str) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvidencePackageVerificationError(
            f"Evidence package {key.replace('_', ' ')} is invalid."
        )
    return value


def _validate_payload_documents(archive: ZipFile, *, incident_id: str) -> None:
    incident = _read_payload_json(archive, "incident.json")
    normalized = _read_payload_json(archive, "normalized-data.json")
    findings = _read_payload_json(archive, "findings.json")
    imagery = _read_payload_json(archive, "imagery-manifests.json")
    source_links = _read_payload_json(archive, "source-links.json")
    if not isinstance(incident, dict) or not isinstance(normalized, dict):
        raise EvidencePackageVerificationError(
            "Evidence package JSON payload shapes are invalid."
        )
    declared_incident_ids = tuple(
        value
        for key in ("event_id", "incident_id")
        if isinstance((value := incident.get(key)), str) and value.strip()
    )
    if declared_incident_ids and any(
        value != incident_id for value in declared_incident_ids
    ):
        raise EvidencePackageVerificationError(
            "Evidence package incident identity is inconsistent."
        )
    if (
        not isinstance(findings, list)
        or any(not isinstance(item, dict) for item in findings)
        or not isinstance(imagery, list)
        or any(not isinstance(item, dict) for item in imagery)
        or not isinstance(source_links, list)
        or any(
            not isinstance(item, str) or not item.startswith("https://")
            for item in source_links
        )
    ):
        raise EvidencePackageVerificationError(
            "Evidence package JSON payload shapes are invalid."
        )


def _read_payload_json(archive: ZipFile, path: str) -> object:
    try:
        return json.loads(archive.read(path))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise EvidencePackageVerificationError(
            f"Evidence package JSON payload is invalid: {path}."
        ) from error


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
