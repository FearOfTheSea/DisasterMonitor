import importlib.util
import tarfile
from pathlib import Path

import pytest

_BACKUP_SCRIPT = Path(__file__).parents[4] / "scripts" / "operational_backup.py"
_BACKUP_SPEC = importlib.util.spec_from_file_location(
    "operational_backup_script", _BACKUP_SCRIPT
)
assert _BACKUP_SPEC is not None and _BACKUP_SPEC.loader is not None
_BACKUP_MODULE = importlib.util.module_from_spec(_BACKUP_SPEC)
_BACKUP_SPEC.loader.exec_module(_BACKUP_MODULE)
BackupError = _BACKUP_MODULE.BackupError
create_backup = _BACKUP_MODULE.create_backup
restore_backup = _BACKUP_MODULE.restore_backup
validate_backup = _BACKUP_MODULE.validate_backup


def _roots(tmp_path: Path) -> dict[str, Path]:
    roots = {
        "operational_blobs": tmp_path / "blobs",
        "event_media": tmp_path / "media",
        "ground_imagery": tmp_path / "ground",
        "field_reports": tmp_path / "field-reports",
        "operator_workspace": tmp_path / "operator-workspace",
    }
    for component, root in roots.items():
        root.mkdir(parents=True)
        (root / f"{component}.json").write_text(component, encoding="utf-8")
    return roots


def test_backup_validate_and_restore_round_trip_filesystem_components(
    tmp_path: Path,
) -> None:
    roots = _roots(tmp_path / "source")
    archive = tmp_path / "backup.tar.gz"

    create_backup(
        backup_path=archive,
        database_url=None,
        component_roots=roots,
        filesystem_only=True,
    )
    manifest = validate_backup(archive)
    assert manifest["schema_version"] == "dm.operational-backup.v3"
    assert set(manifest["included_components"]) == set(roots)
    assert manifest["database_contents"]
    assert manifest["database_mode"] == "filesystem_only"

    restored = _roots(tmp_path / "restored")
    for root in restored.values():
        next(root.iterdir()).write_text("old", encoding="utf-8")
    restore_backup(
        backup_path=archive,
        database_url=None,
        component_roots=restored,
        confirmation="REPLACE_OPERATIONAL_STATE",
    )
    for component, root in restored.items():
        assert next(root.iterdir()).read_text(encoding="utf-8") == component


def test_restore_requires_explicit_replacement_confirmation(tmp_path: Path) -> None:
    roots = _roots(tmp_path / "source")
    archive = tmp_path / "backup.tar.gz"
    create_backup(
        backup_path=archive,
        database_url=None,
        component_roots=roots,
        filesystem_only=True,
    )

    with pytest.raises(BackupError, match="REPLACE_OPERATIONAL_STATE"):
        restore_backup(
            backup_path=archive,
            database_url=None,
            component_roots=_roots(tmp_path / "restored"),
            confirmation="no",
        )


def test_legacy_archive_requires_explicit_partial_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = _roots(tmp_path / "source")
    archive = tmp_path / "legacy.tar.gz"
    with monkeypatch.context() as patch:
        patch.setattr(_BACKUP_MODULE, "SCHEMA_VERSION", "dm.operational-backup.v2")
        patch.setattr(_BACKUP_MODULE, "COMPONENTS", _BACKUP_MODULE.LEGACY_COMPONENTS)
        create_backup(
            backup_path=archive,
            database_url=None,
            component_roots=roots,
            filesystem_only=True,
        )
    assert validate_backup(archive)["schema_version"] == "dm.operational-backup.v2"
    restored = _roots(tmp_path / "restored")
    with pytest.raises(BackupError, match="allow-legacy-partial-restore"):
        restore_backup(
            backup_path=archive,
            database_url=None,
            component_roots=restored,
            confirmation="REPLACE_OPERATIONAL_STATE",
        )
    restore_backup(
        backup_path=archive,
        database_url=None,
        component_roots=restored,
        confirmation="REPLACE_OPERATIONAL_STATE",
        allow_legacy_partial_restore=True,
    )
    assert (restored["field_reports"] / "field_reports.json").read_text() == (
        "field_reports"
    )


def test_database_restore_failure_rolls_back_filesystem_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _roots(tmp_path / "source")
    archive = tmp_path / "backup.tar.gz"
    monkeypatch.setattr(
        _BACKUP_MODULE,
        "_dump_database",
        lambda database_url, target: target.write_bytes(b"fixture-dump"),
    )
    create_backup(
        backup_path=archive,
        database_url="postgresql://fixture",
        component_roots=source,
        writers_paused=True,
    )
    restored = _roots(tmp_path / "restored")
    for root in restored.values():
        next(root.iterdir()).write_text("original", encoding="utf-8")

    def fail_restore(database_url: str, dump_path: Path) -> None:
        raise BackupError("fixture database restore failed")

    monkeypatch.setattr(_BACKUP_MODULE, "_restore_database", fail_restore)
    with pytest.raises(BackupError, match="database restore failed"):
        restore_backup(
            backup_path=archive,
            database_url="postgresql://fixture",
            component_roots=restored,
            confirmation="REPLACE_OPERATIONAL_STATE",
            writers_paused=True,
        )

    assert all(
        next(root.iterdir()).read_text(encoding="utf-8") == "original"
        for root in restored.values()
    )


def test_unsafe_duplicate_archive_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.addfile(tarfile.TarInfo("manifest.json"))
        member = tarfile.TarInfo("manifest.json")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        output.addfile(member)

    with pytest.raises(BackupError, match="non-regular member"):
        validate_backup(archive)


def test_mounted_restore_replaces_contents_without_renaming_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _roots(tmp_path / "source")
    archive = tmp_path / "backup.tar.gz"
    create_backup(
        backup_path=archive,
        database_url=None,
        component_roots=source,
        filesystem_only=True,
    )
    restored = _roots(tmp_path / "restored")
    field_root = restored["field_reports"]
    (field_root / "field_reports.json").write_text("changed", encoding="utf-8")
    original_ismount = _BACKUP_MODULE.os.path.ismount
    monkeypatch.setattr(
        _BACKUP_MODULE.os.path,
        "ismount",
        lambda path: path == field_root or original_ismount(path),
    )

    restore_backup(
        backup_path=archive,
        database_url=None,
        component_roots=restored,
        confirmation="REPLACE_OPERATIONAL_STATE",
    )

    assert field_root.is_dir()
    assert (field_root / "field_reports.json").read_text() == "field_reports"
    assert (field_root / "field_reports.json").stat().st_uid == field_root.stat().st_uid
