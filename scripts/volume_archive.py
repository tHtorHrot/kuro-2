"""Streaming cold volume archive. Executed only in a network-free operations container."""

import os
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOTS = {
    "documents": Path("/volumes/documents"),
    "qdrant": Path("/volumes/qdrant"),
    "models": Path("/volumes/models"),
}


def safe_name(name):
    path = PurePosixPath(name)
    return bool(
        path.parts
        and path.parts[0] in ROOTS
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
    )


def pack(roots, stream):
    for path in roots.values():
        if not path.is_dir():
            raise ValueError("volume missing")
        for entry in path.rglob("*"):
            if entry.is_symlink() and not entry.resolve().is_relative_to(path.resolve()):
                raise ValueError("volume symlink escapes source")
    with tarfile.open(fileobj=stream, mode="w|", dereference=False) as archive:
        for name, path in roots.items():
            archive.add(path, arcname=name)


def unpack(roots, stream, *, chown=False):
    # Empty target roots are essential: never overwrite a running/restored installation.
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            raise ValueError("restore target volume is not empty")
    base = next(iter(roots.values())).parent
    if any(path.parent != base or path.name != name for name, path in roots.items()):
        raise ValueError("restore roots do not share the expected parent")
    seen = set()
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            if (
                not safe_name(member.name)
                or member.name in seen
                or not (member.isfile() or member.isdir() or member.issym() or member.islnk())
            ):
                raise ValueError("unsafe archive member")
            seen.add(member.name)
            archive.extract(member, base, filter="data")
    if chown:
        for root in roots.values():
            for path in [root, *root.rglob("*")]:
                os.chown(path, 10001, 10001, follow_symlinks=False)
            root.chmod(0o700)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["pack"]:
            pack(ROOTS, sys.stdout.buffer)
        elif sys.argv[1:] == ["unpack"]:
            unpack(ROOTS, sys.stdin.buffer, chown=True)
        else:
            raise ValueError("expected pack or unpack")
    except (OSError, ValueError, tarfile.TarError):
        print(
            "Volume archive operation failed; targets must be private/empty/safe.", file=sys.stderr
        )
        raise SystemExit(2) from None
