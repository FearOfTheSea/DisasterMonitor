"""Atomic private local writes, with verified Windows ACLs and migration backups."""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

_ACL_SCRIPT = r"""
$ErrorActionPreference='Stop'
$path=$env:DM_PRIVATE_STATE_PATH
$identity=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$directory=[System.IO.Directory]::Exists($path)
if ($directory) { $existing=[System.IO.Directory]::GetAccessControl($path) }
else { $existing=[System.IO.File]::GetAccessControl($path) }
$owner=$existing.GetOwner([System.Security.Principal.SecurityIdentifier])
if ($env:DM_PRIVATE_STATE_NEW -eq '1') { $owner=$identity }
$allowed=@($identity.Value,$owner.Value) | Select-Object -Unique
if ($env:DM_PRIVATE_STATE_SET -eq '1') {
  $acl=$existing
  if ($env:DM_PRIVATE_STATE_NEW -eq '1') { $acl.SetOwner($identity) }
  $explicit=$acl.GetAccessRules($true,$false,$identity.GetType())
  foreach ($rule in $explicit) {
    $acl.RemoveAccessRuleSpecific($rule)
  }
  $acl.SetAccessRuleProtection($true,$false)
  foreach ($sid in $allowed) {
    $principal=[System.Security.Principal.SecurityIdentifier]::new($sid)
    if ($directory) {
      $rule=[System.Security.AccessControl.FileSystemAccessRule]::new(
        $principal,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    } else {
      $rule=[System.Security.AccessControl.FileSystemAccessRule]::new(
        $principal,'FullControl','Allow')
    }
    $acl.AddAccessRule($rule)
  }
  if ($directory) { [System.IO.Directory]::SetAccessControl($path,$acl) }
  else { [System.IO.File]::SetAccessControl($path,$acl) }
}
if ($directory) { $verified=[System.IO.Directory]::GetAccessControl($path) }
else { $verified=[System.IO.File]::GetAccessControl($path) }
$verifiedOwner=$verified.GetOwner($identity.GetType())
if ($verifiedOwner.Value -ne $owner.Value) { throw 'Private state owner changed.' }
if (-not $verified.AreAccessRulesProtected) {
  throw 'Private ACL inheritance is enabled.'
}
$rules=$verified.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])
foreach ($rule in $rules) {
  if ($rule.AccessControlType -eq 'Allow' -and
      $rule.IdentityReference.Value -notin $allowed) {
    throw 'Unexpected principal can access private state.'
  }
}
$ownerAccess=$rules | Where-Object {
  $_.IdentityReference.Value -eq $identity.Value -and $_.AccessControlType -eq 'Allow'
}
if (-not $ownerAccess) {
  throw 'Current owner access was not preserved.'
}
"""


def _checked_path(path: Path) -> Path:
    resolved = path.resolve()
    if (
        len(resolved.parts) < 3
        or path.is_symlink()
        or any(parent.is_symlink() for parent in path.parents)
    ):
        raise ValueError("Private state requires a concrete configured path.")
    return resolved


def _acl(path: Path, *, apply: bool, new_file: bool = False) -> None:
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _ACL_SCRIPT],
        env={
            **os.environ,
            "DM_PRIVATE_STATE_PATH": str(path),
            "DM_PRIVATE_STATE_SET": "1" if apply else "0",
            "DM_PRIVATE_STATE_NEW": "1" if new_file else "0",
        },
        capture_output=True,
        check=True,
        timeout=15,
    )


def verify_private_path(path: Path) -> bool:
    target = _checked_path(path)
    if os.name == "nt":
        try:
            _acl(target, apply=False)
            return True
        except subprocess.CalledProcessError:
            return False
    return target.stat().st_mode & 0o777 == (0o700 if target.is_dir() else 0o600)


def restrict_private_path(path: Path, *, backup: bool = False) -> None:
    target = _checked_path(path)
    if backup and target.is_file():
        preserved = target.with_suffix(target.suffix + ".privacy-backup")
        if not preserved.exists():
            preserved.touch(exist_ok=False)
            restrict_private_path(preserved)
            shutil.copyfile(target, preserved)
    if os.name == "nt":
        _acl(target, apply=True)
    else:
        target.chmod(0o700 if target.is_dir() else 0o600)


def atomic_private_write(path: Path, content: str | bytes) -> None:
    target = _checked_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.touch(exist_ok=False)
    try:
        if os.name == "nt":
            _acl(temporary, apply=True, new_file=True)
        else:
            restrict_private_path(temporary)
        with temporary.open("wb") as stream:
            stream.write(
                content.encode("utf-8") if isinstance(content, str) else content
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
