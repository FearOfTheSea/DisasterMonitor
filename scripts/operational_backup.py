"""Create, validate, and explicitly restore an operational-state archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "dm.operational-backup.v2"
CONFIRMATION = "REPLACE_OPERATIONAL_STATE"
COMPONENTS = {
    "operational_blobs": "files/operational-blobs",
    "event_media": "files/event-media",
    "ground_imagery": "files/ground-imagery",
}
DATABASE_CONTENTS = (
    "incident_watches",
    "normalized_observations",
    "source_snapshots",
    "ground_imagery_metadata",
    "audit_events",
)


class BackupError(RuntimeError):
    """The requested backup operation failed closed."""


def create_backup(
    *,
    backup_path: Path,
    database_url: str | None,
    component_roots: dict[str, Path],
    filesystem_only: bool = False,
    writers_paused: bool = False,
) -> Path:
    """Build one self-describing archive from explicit operational roots."""
    if database_url is None and not filesystem_only:
        raise BackupError(
            "A database URL is required; pass --filesystem-only only for development."
        )
    if database_url is not None and not writers_paused:
        raise BackupError("Database-and-blob backup requires a confirmed writer pause.")
    backup_path = backup_path.resolve()
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="operational-backup-", dir=backup_path.parent
    ) as temporary:
        staging = Path(temporary)
        files_root = staging / "files"
        files_root.mkdir()
        copied_components: list[str] = []
        for component, relative_target in COMPONENTS.items():
            source = component_roots.get(component)
            if source is None:
                raise BackupError(f"Missing configured root for {component}.")
            target = staging / relative_target
            _copy_tree(source, target, component)
            copied_components.append(component)

        database_mode = "filesystem_only"
        if database_url is not None:
            database_mode = "pg_dump_custom"
            _dump_database(database_url, staging / "database.dump")
        manifest = _build_manifest(
            staging,
            database_mode=database_mode,
            included_components=tuple(copied_components),
        )
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary_archive = backup_path.with_suffix(backup_path.suffix + ".tmp")
        try:
            with tarfile.open(temporary_archive, "w:gz") as archive:
                for path in sorted(staging.rglob("*")):
                    archive.add(path, arcname=path.relative_to(staging))
            temporary_archive.replace(backup_path)
        finally:
            temporary_archive.unlink(missing_ok=True)
    validate_backup(backup_path)
    return backup_path


def validate_backup(backup_path: Path) -> dict[str, Any]:
    """Validate archive paths, manifest checksums, and required components."""
    backup_path = backup_path.resolve()
    try:
        archive = tarfile.open(backup_path, "r:gz")
    except (OSError, tarfile.TarError) as error:
        raise BackupError(f"Could not open backup archive: {backup_path}") from error
    with archive:
        members = {member.name: member for member in archive.getmembers()}
        _validate_members(members)
        manifest_member = members.get("manifest.json")
        if manifest_member is None:
            raise BackupError("Backup archive has no manifest.")
        handle = archive.extractfile(manifest_member)
        if handle is None:
            raise BackupError("Backup manifest could not be read.")
        try:
            manifest = json.loads(handle.read().decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise BackupError("Backup manifest is invalid JSON.") from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != SCHEMA_VERSION
        ):
            raise BackupError("Unsupported operational backup schema.")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise BackupError("Backup manifest has no file checksums.")
        for entry in entries:
            if not isinstance(entry, dict):
                raise BackupError("Backup file manifest entry is invalid.")
            name = _required_text(entry, "path")
            member = members.get(name)
            if member is None or not member.isfile():
                raise BackupError(f"Backup file is missing: {name}")
            byte_count = entry.get("byte_count")
            if not isinstance(byte_count, int) or byte_count < 0:
                raise BackupError(f"Backup byte count is invalid: {name}")
            if member.size != byte_count:
                raise BackupError(f"Backup byte count mismatch: {name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise BackupError(f"Backup file cannot be read: {name}")
            digest = _stream_sha256(handle)
            if digest != _required_text(entry, "sha256"):
                raise BackupError(f"Backup checksum mismatch: {name}")
        required = set(COMPONENTS.values())
        if manifest.get("database_mode") == "pg_dump_custom":
            required.add("database.dump")
        for prefix in required:
            if not any(
                name == prefix or name.startswith(prefix + "/") for name in members
            ):
                raise BackupError(f"Backup component is missing: {prefix}")
        return manifest


def restore_backup(
    *,
    backup_path: Path,
    database_url: str | None,
    component_roots: dict[str, Path],
    confirmation: str,
    writers_paused: bool = False,
) -> dict[str, Any]:
    """Restore an archive only after explicit replacement confirmation."""
    if confirmation != CONFIRMATION:
        raise BackupError(f"Pass {CONFIRMATION} to authorize replacement.")
    manifest = validate_backup(backup_path)
    if manifest.get("database_mode") == "pg_dump_custom" and database_url is None:
        raise BackupError("A database URL is required to restore database state.")
    if manifest.get("database_mode") == "pg_dump_custom" and not writers_paused:
        raise BackupError("Database restore requires a confirmed writer pause.")
    with tempfile.TemporaryDirectory(prefix="operational-restore-") as temporary:
        staging = Path(temporary)
        _extract_archive(backup_path, staging)
        _restore_components(
            staging=staging,
            component_roots=component_roots,
            database_url=database_url,
            restore_database=manifest.get("database_mode") == "pg_dump_custom",
        )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("backup", "restore", "validate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--archive", type=Path, required=True)
        if command != "validate":
            subparser.add_argument(
                "--database-url", default=os.getenv("OPERATIONAL_DATABASE_URL")
            )
            subparser.add_argument("--operational-blobs", type=Path, required=True)
            subparser.add_argument("--event-media", type=Path, required=True)
            subparser.add_argument("--ground-imagery", type=Path, required=True)
        if command == "backup":
            subparser.add_argument("--filesystem-only", action="store_true")
        if command in {"backup", "restore"}:
            subparser.add_argument("--writers-paused", action="store_true")
        if command == "restore":
            subparser.add_argument("--confirm", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "validate":
            manifest = validate_backup(arguments.archive)
            print(json.dumps(manifest, indent=2, sort_keys=True))
        else:
            roots = {
                "operational_blobs": arguments.operational_blobs,
                "event_media": arguments.event_media,
                "ground_imagery": arguments.ground_imagery,
            }
            if arguments.command == "backup":
                path = create_backup(
                    backup_path=arguments.archive,
                    database_url=arguments.database_url,
                    component_roots=roots,
                    filesystem_only=arguments.filesystem_only,
                    writers_paused=arguments.writers_paused,
                )
                print(f"Operational backup written to {path}")
            else:
                restore_backup(
                    backup_path=arguments.archive,
                    database_url=arguments.database_url,
                    component_roots=roots,
                    confirmation=arguments.confirm,
                    writers_paused=arguments.writers_paused,
                )
                print(f"Operational state restored from {arguments.archive}")
    except (
        BackupError,
        OSError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as error:
        print(f"Operational backup failed closed: {error}")
        return 2
    return 0


def _build_manifest(
    staging: Path, *, database_mode: str, included_components: tuple[str, ...]
) -> dict[str, Any]:
    files = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(staging).as_posix()
        files.append(
            {
                "path": relative,
                "byte_count": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "database_mode": database_mode,
        "database_contents": list(DATABASE_CONTENTS),
        "included_components": list(included_components),
        "files": files,
    }


def _copy_tree(source: Path, target: Path, component: str) -> None:
    source = source.resolve()
    if not source.is_dir():
        raise BackupError(f"Configured {component} root is not a directory: {source}")
    symlinks = [path for path in source.rglob("*") if path.is_symlink()]
    if symlinks:
        raise BackupError(
            f"Configured {component} root contains a symbolic link: {symlinks[0]}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False)


def _dump_database(database_url: str, target: Path) -> None:
    completed = subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(target), "--dbname", database_url],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise BackupError("pg_dump could not create the operational database dump.")


def _restore_database(database_url: str, dump_path: Path) -> None:
    completed = subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--exit-on-error",
            "--single-transaction",
            "--dbname",
            database_url,
            str(dump_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise BackupError("pg_restore could not replace the operational database.")


def _extract_archive(archive_path: Path, target: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        _validate_members(members)
        for member in members.values():
            destination = (target / member.name).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise BackupError(
                    "Backup archive path escaped its restore staging root."
                )
        archive.extractall(target, filter="data")


def _restore_components(
    *,
    staging: Path,
    component_roots: dict[str, Path],
    database_url: str | None,
    restore_database: bool,
) -> None:
    prepared: list[tuple[Path, Path, Path]] = []
    swapped: list[tuple[Path, Path]] = []
    try:
        for component, relative_source in COMPONENTS.items():
            source = staging / relative_source
            target = component_roots.get(component)
            if target is None:
                raise BackupError(f"Missing configured root for {component}.")
            _validate_restore_target(target)
            target = target.resolve(strict=False)
            if not source.is_dir():
                raise BackupError(f"Restored component is missing: {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            candidate = target.parent / f".{target.name}.restore-{uuid4().hex}"
            backup = target.parent / f".{target.name}.previous-{uuid4().hex}"
            shutil.copytree(source, candidate, symlinks=False)
            prepared.append((target, candidate, backup))

        for target, candidate, backup in prepared:
            if target.exists():
                target.replace(backup)
            candidate.replace(target)
            swapped.append((target, backup))

        if restore_database:
            assert database_url is not None
            _restore_database(database_url, staging / "database.dump")
    except Exception:
        for target, backup in reversed(swapped):
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                backup.replace(target)
        raise
    finally:
        for _, candidate, backup in prepared:
            if candidate.exists():
                shutil.rmtree(candidate)
            if backup.exists():
                shutil.rmtree(backup)


def _validate_restore_target(target: Path) -> None:
    if target == Path(target.anchor) or target == Path.home().resolve():
        raise BackupError(f"Restore target is too broad: {target}")
    if target.is_symlink():
        raise BackupError(f"Restore target cannot be a symbolic link: {target}")


def _validate_members(members: dict[str, tarfile.TarInfo]) -> None:
    for name, member in members.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise BackupError(f"Backup archive path is unsafe: {name}")
        if not (member.isdir() or member.isfile()):
            raise BackupError(f"Backup archive contains a non-regular member: {name}")


def _file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return _stream_sha256(handle)


def _stream_sha256(handle: Any) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    return "sha256:" + digest.hexdigest()


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise BackupError(f"Backup manifest field {key} is invalid.")
    return item


if __name__ == "__main__":
    raise SystemExit(main())
