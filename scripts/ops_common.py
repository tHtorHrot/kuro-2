"""Small host-side operations primitives; no shell interpolation or credential logging."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

SOURCE_DIRS = ("src", "migrations", "tests", "scripts")
SOURCE_FILES = ("Dockerfile", "pyproject.toml", "uv.lock", "alembic.ini")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(root):
    paths = set()
    for folder in SOURCE_DIRS:
        paths.update(
            p
            for p in (root / folder).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py", ".mjs", ".sql"}
        )
    paths.update(root / name for name in SOURCE_FILES if (root / name).is_file())
    paths.update(root.glob("compose*.yaml"))
    files = {p.relative_to(root).as_posix(): sha256(p) for p in sorted(paths)}
    digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "algorithm": "sha256",
        "scope": "src/migrations/tests/scripts *.py,*.sql,*.mjs; "
        "Dockerfile/pyproject.toml/uv.lock/alembic.ini/compose*.yaml; exclude __pycache__",
        "hash": digest,
        "files": files,
    }


class OpsError(ValueError):
    pass


class Compose:
    def __init__(self, root, project, files):
        self.root, self.project, self.files = Path(root), project, list(files)
        if not files:
            raise OpsError("Compose files required")
        self.prefix = ["docker", "compose", "-p", project]
        for file in files:
            path = Path(file)
            if not path.is_absolute():
                path = self.root / path
            if not path.is_file():
                raise OpsError("Compose file missing")
            self.prefix += ["-f", str(path)]

    def run(self, *args, output=None, input_stream=None, timeout=120):
        try:
            result = subprocess.run(
                self.prefix + list(args),
                cwd=self.root,
                stdout=output if output is not None else subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=input_stream,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise OpsError("Docker/Compose operation unavailable or timed out") from None
        if result.returncode:
            raise OpsError("Docker/Compose operation failed; private details withheld")
        return result.stdout

    def ps(self):
        raw = self.run("ps", "--all", "--format", "json").decode()
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            return [json.loads(line) for line in raw.splitlines() if line.strip()]

    def image_identity(self, container_id):
        # Inspect only selected image fields. Environment/credential fields never enter reports.
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.Image}}", container_id],
                capture_output=True,
                timeout=10,
                check=False,
            )
            image_id = result.stdout.decode().strip()
            if result.returncode or not image_id.startswith("sha256:"):
                raise OpsError("Container image identity unavailable")
            digest = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image_id],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if digest.returncode:
                raise OpsError("Image digest inspection failed")
            return {"image_id": image_id, "repo_digests": json.loads(digest.stdout) or []}
        except (OSError, ValueError, subprocess.SubprocessError):
            raise OpsError("Image identity unavailable") from None

    def sql(self, statement, *, database="jarvis"):
        return (
            self.run(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                database,
                "-X",
                "-A",
                "-t",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                statement,
            )
            .decode()
            .strip()
        )


def windows_private_dacl(path):
    # Persist only the modified access section, without setting owner/group/audit.
    # Set-Acl can request SeSecurityPrivilege even for an otherwise ordinary folder.
    # Pass the path as environment data so quoting cannot turn a path into code.
    script = ";".join(
        [
            "$ErrorActionPreference='Stop'",
            "$kuroSid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User",
            "$kuroDir=Get-Item -LiteralPath $env:KURO_PRIVATE_DIR -ErrorAction Stop",
            "$kuroAccess=[System.Security.AccessControl.AccessControlSections]::Access",
            "$kuroAcl=$kuroDir.GetAccessControl($kuroAccess)",
            "$kuroAcl.SetAccessRuleProtection($true,$false)",
            "foreach($kuroExisting in @($kuroAcl.GetAccessRules($true,$false,"
            "[System.Security.Principal.SecurityIdentifier])))"
            "{$kuroAcl.RemoveAccessRuleSpecific($kuroExisting)}",
            "$kuroFlags=[System.Security.AccessControl.InheritanceFlags]::ContainerInherit"
            " -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit",
            "$kuroRights=[System.Security.AccessControl.FileSystemRights]::FullControl",
            "$kuroRule=New-Object -TypeName System.Security.AccessControl.FileSystemAccessRule"
            " -ArgumentList @($kuroSid,$kuroRights,$kuroFlags,"
            "[System.Security.AccessControl.PropagationFlags]::None,"
            "[System.Security.AccessControl.AccessControlType]::Allow)",
            "$kuroAcl.AddAccessRule($kuroRule)",
            "$kuroDir.SetAccessControl($kuroAcl)",
            "$kuroVerify=$kuroDir.GetAccessControl($kuroAccess)",
            "$kuroRules=@($kuroVerify.GetAccessRules($true,$true,"
            "[System.Security.Principal.SecurityIdentifier]))",
            "if(-not $kuroVerify.AreAccessRulesProtected -or $kuroRules.Count -ne 1)"
            "{throw 'Private DACL verification failed'}",
            "if($kuroRules[0].IdentityReference.Value -ne $kuroSid.Value -or "
            "$kuroRules[0].AccessControlType -ne 'Allow' -or "
            "$kuroRules[0].FileSystemRights -ne $kuroRights -or "
            "$kuroRules[0].InheritanceFlags -ne $kuroFlags -or "
            "$kuroRules[0].PropagationFlags -ne 'None' -or $kuroRules[0].IsInherited)"
            "{throw 'Private DACL rule verification failed'}",
            "Write-Output 'KURO_PRIVATE_DACL_OK'",
        ]
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "KURO_PRIVATE_DIR": str(Path(path).resolve())},
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode or result.stdout.strip() != b"KURO_PRIVATE_DACL_OK":
        raise OpsError(
            f"Private folder DACL verification failed (PowerShell exit={result.returncode})"
        )


def private_folder(path):
    path = Path(path)
    if path.is_symlink():
        raise OpsError("Private folder cannot be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    if os.name == "nt":
        windows_private_dacl(path)
    return path
