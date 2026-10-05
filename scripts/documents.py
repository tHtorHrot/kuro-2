"""Stream bytes to the trusted Docker CLI; never use PowerShell text redirection."""

import argparse
import subprocess
from pathlib import Path
from uuid import UUID


def run(argv=None, *, runner=subprocess.run):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Dokumen privat Jarvis Tahap 3")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("file", type=Path)
    add.add_argument(
        "--data-class",
        choices=["private", "restricted"],
        default="private",
        help="private permits selected excerpts in /askdoc cloud requests",
    )
    add.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    for name in ("info", "delete", "retry"):
        commands.add_parser(name).add_argument("document_id", type=UUID)
    for name in ("list", "status", "check"):
        commands.add_parser(name)
    args = parser.parse_args(argv)
    command = [
        "docker",
        "compose",
        "-f",
        str(root / "compose.yaml"),
        "-f",
        str(root / "compose.assistant.yaml"),
        "-f",
        str(root / "compose.knowledge.yaml"),
        "--profile",
        "knowledge-ops",
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "knowledge-ops",
    ]
    if args.command == "add":
        path = args.file
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 20 * 1024**2:
            raise ValueError("File harus tersedia, bukan symlink, dan berukuran 1 byte–20 MiB.")
        if path.suffix.lower() not in {".pdf", ".docx", ".png", ".jpg", ".jpeg"}:
            raise ValueError("File harus PDF, DOCX, PNG atau JPG. Konversi .doc menjadi .docx.")
        command += [
            "documents-import",
            f"--filename={path.name}",
            "--data-class",
            args.data_class,
            "--ocr",
            args.ocr,
        ]
        with path.open("rb") as source:
            return runner(command, cwd=root, stdin=source, check=False).returncode
    if args.command in {"status", "check"}:
        command += ["knowledge-" + args.command]
    else:
        command += ["documents-" + args.command]
        if args.command != "list":
            command += [str(args.document_id)]
    return runner(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
