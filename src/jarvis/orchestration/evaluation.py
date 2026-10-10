"""Evaluation System — Bagian 6.1/6.5 MD.

Worker mengusulkan completion; evaluator menentukan passed/failed/needs-human.
Pemeriksaan deterministik dulu; model/human review hanya untuk yang material.
Maksimal satu repair pass otomatis sebagai default awal.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EvalResult:
    passed: bool
    needs_human: bool
    checks: dict
    reason: str = ""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def eval_code(
    *,
    files: dict[str, str],
    required_files: list[str] | None = None,
    forbidden: list[str] | None = None,
) -> EvalResult:
    checks: dict = {}
    required_files = required_files or []
    forbidden = forbidden or ["../", ".git/", "/etc/", "credentials"]
    checks["has_files"] = bool(files)
    missing = [f for f in required_files if f not in files]
    checks["missing"] = missing
    bad = [f for f in files if any(p in f for p in forbidden)]
    checks["forbidden_paths"] = bad
    empty = [f for f, c in files.items() if not c.strip()]
    checks["empty_files"] = empty
    passed = not missing and not bad and bool(files) and not empty
    return EvalResult(
        passed=passed,
        needs_human=False,
        checks=checks,
        reason="ok" if passed else "code_checks_failed",
    )


def eval_data(
    *, rows: list[dict], expected_count: int | None = None, numeric_fields: list[str] | None = None
) -> EvalResult:
    checks: dict = {"row_count": len(rows)}
    if expected_count is not None:
        checks["expected"] = expected_count
        if len(rows) != expected_count:
            return EvalResult(False, False, checks, "row_count_mismatch")
    for field_name in numeric_fields or []:
        try:
            total = sum(float(r.get(field_name, 0) or 0) for r in rows)
        except (TypeError, ValueError):
            return EvalResult(False, False, checks, f"non_numeric_{field_name}")
        checks[f"sum_{field_name}"] = total
    return EvalResult(True, False, checks, "ok")


_CITE = re.compile(r"\[(S\d+)\]")


def eval_research(
    *, answer: str, source_ids: list[str], supported_claims: int = 0, total_claims: int = 0
) -> EvalResult:
    """Citation coverage dan supported claims; no fabricated citations."""
    labels = _CITE.findall(answer)
    checks: dict = {"labels": labels, "sources": source_ids}
    unknown = [label for label in labels if label not in source_ids]
    checks["unknown_labels"] = unknown
    if unknown or not labels:
        return EvalResult(False, False, checks, "citation_invalid")
    checks["coverage"] = f"{len(set(labels))}/{len(source_ids)}"
    if total_claims > 0 and supported_claims < total_claims:
        return EvalResult(False, True, checks, "claims_unsupported_needs_human")
    return EvalResult(True, False, checks, "ok")


def eval_calendar(*, fingerprint: str, expected_fingerprint: str) -> EvalResult:
    ok = bool(fingerprint) and fingerprint == expected_fingerprint
    return EvalResult(ok, False, {"match": ok}, "ok" if ok else "fingerprint_mismatch")


def eval_communication(
    *, recipient: str, expected_recipient: str, payload_hash: str, approved_hash: str | None
) -> EvalResult:
    if recipient != expected_recipient:
        return EvalResult(False, False, {"recipient": recipient}, "recipient_mismatch")
    if approved_hash is None:
        return EvalResult(False, True, {"payload": payload_hash}, "send_needs_approval")
    if payload_hash != approved_hash:
        return EvalResult(False, False, {"payload": payload_hash}, "approval_payload_changed")
    return EvalResult(True, False, {"recipient": recipient}, "ok")
