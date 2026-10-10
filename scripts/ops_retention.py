"""Explicit retention for this tool's encrypted backups only; preview by default."""

import argparse
import re
from pathlib import Path

from ops_common import OpsError

PATTERN = re.compile(r"kuro-complete-\d{8}T\d{12}Z\.tar\.cms")


def expired_backups(folder, keep):
    if not 1 <= keep <= 365 or folder.is_symlink():
        raise OpsError("Keep must be 1..365; backup folder cannot be a symlink")
    files = sorted(p for p in folder.iterdir() if PATTERN.fullmatch(p.name))
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise OpsError("Encrypted backup inventory contains non-regular paths")
    return files[:-keep]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    p.add_argument("--keep", type=int, default=7)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    for path in expired_backups(args.folder, args.keep):
        print(path.name)
        if args.apply:
            path.unlink()
            sidecar = path.with_name(path.name + ".sha256")
            report = path.with_name(path.name.removesuffix(".tar.cms") + ".json")
            for extra in (sidecar, report):
                if extra.is_symlink():
                    raise OpsError("Retention sidecar cannot be a symlink")
                extra.unlink(missing_ok=True)
