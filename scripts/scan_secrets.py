"""Stdlib secret hygiene scan; no third-party binary required.

Fails closed on realistic secret shapes outside the allowlist. Prints
file:line + rule names ONLY — never matched values. Intentional test
fixtures are allowlisted per (file, rule) below, never by value.
"""

import argparse
import re
from pathlib import Path

RULES = [
    ("openrouter_key", re.compile(r"sk-or-[A-Za-z0-9]{20,}")),
    ("jarvis_token", re.compile(r"jv[tp]1\.[A-Za-z0-9_\-]{20,}")),
    ("generic_api_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("telegram_bot_token", re.compile(r"\b\d{6,16}:[A-Za-z0-9_\-]{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}")),
]

SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        ".secrets",
        "backups",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
    }
)
SKIP_SUFFIXES = (".zip", ".png", ".jpg", ".jpeg", ".pdf", ".dump", ".cms", ".tar", ".gz")
# Evidence archives may echo historical tool output; live secrets must never
# be committed there in the first place (see SECURITY.md).
EVIDENCE_TREE = ("docs", "evidence")

# Intentional fixtures, auditable here instead of hidden in test files.
ALLOW = frozenset(
    {
        # Fake PEM header inside a safe_content unit test, no key material.
        ("tests/unit/test_assistant_router.py", "private_key_block"),
    }
)


def scan_tree(root: Path) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]) or rel.parts[0] in SKIP_DIRS:
            continue
        if rel.parts[:2] == EVIDENCE_TREE:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:4096]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pattern in RULES:
                if pattern.search(line) and (rel.as_posix(), name) not in ALLOW:
                    hits.append((rel.as_posix(), lineno, name))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    hits = scan_tree(args.root)
    for rel, lineno, name in hits:
        print(f"{rel}:{lineno}:{name}")
    if hits:
        print(f"secret_scan: {len(hits)} finding(s); values withheld")
        return 2
    print("secret_scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
