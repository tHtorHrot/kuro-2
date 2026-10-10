"""Sandbox untuk Coding/Data — Bagian 6.4 MD.

Tiga execution classes: trusted read tools (in-process), credentialed
side-effect tools (via ActionJournal+broker), untrusted code runtime
(wajib sandbox). Launcher menerima image/profile dan mount yang sudah
ditetapkan operator, bukan arbitrary Docker arguments hasil model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_IMAGE = "kuro-sandbox:stable"
DEFAULT_CPUS = "1.0"
DEFAULT_MEMORY = "512m"
DEFAULT_TIMEOUT_SECONDS = 300


class SandboxError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SandboxProfile:
    image: str = DEFAULT_IMAGE
    cpus: str = DEFAULT_CPUS
    memory: str = DEFAULT_MEMORY
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    allow_network: bool = False
    extra_mounts: tuple[str, ...] = ()
    command: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not self.image or len(self.image) > 200 or any(c in self.image for c in " ;|&$`"):
            raise SandboxError("sandbox_image_invalid")
        if self.extra_mounts:
            raise SandboxError("sandbox_mounts_forbidden")
        if not 10 <= self.timeout_seconds <= 1800:
            raise SandboxError("sandbox_timeout_invalid")


def docker_args(profile: SandboxProfile, *, workspace: Path, workdir: str = "/work") -> list[str]:
    """Bangun docker run yang sempit: nonroot, read-only rootfs, writable task dir,
    PID/CPU/RAM/time quotas, network default-deny. Tanpa Docker socket."""
    if profile.allow_network:
        raise SandboxError("sandbox_network_requires_proxy")
    return [
        "docker",
        "run",
        "--rm",
        "--user",
        "65532:65532",
        "--read-only",
        "--network",
        "none",
        "--pids-limit",
        "128",
        "--cpus",
        profile.cpus,
        "--memory",
        profile.memory,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "-v",
        f"{workspace}:/work:rw",
        "-w",
        workdir,
        profile.image,
        *profile.command,
    ]


def validate_execution_class(tool_effect: str, *, in_sandbox: bool) -> None:
    """General code execution tidak boleh membawa credential asisten."""
    if tool_effect in ("code_exec", "workspace_write") and not in_sandbox:
        raise SandboxError("sandbox_required")
