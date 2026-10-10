"""Worker capability protocol — Bagian 6.4 MD.

Worker berkomunikasi dengan broker memakai capability yang terikat
owner/task/run/expiry/tools. Broker menentukan principal dari credential/
capability, bukan mempercayai owner_id kiriman worker. Authority worker
adalah irisan user grant, task grant, role allowlist dan tool requirements.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WorkerCapability:
    owner_id: UUID
    task_id: UUID
    run_id: UUID
    expires_at: int
    tools: frozenset[str]
    token: str = ""


def mint_capability(
    *,
    secret: str,
    owner_id: UUID,
    task_id: UUID,
    run_id: UUID,
    ttl_seconds: int,
    tools: frozenset[str],
) -> WorkerCapability:
    if ttl_seconds < 60 or ttl_seconds > 7200:
        raise ValueError("invalid_capability_ttl")
    expires = int(time.time()) + ttl_seconds
    body = json.dumps(
        {
            "o": str(owner_id),
            "t": str(task_id),
            "r": str(run_id),
            "e": expires,
            "tools": sorted(tools),
        },
        separators=(",", ":"),
    )
    token = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return WorkerCapability(owner_id, task_id, run_id, expires, tools, f"{body}.{token}")


def verify_capability(secret: str, token: str) -> WorkerCapability:
    try:
        body, sig = token.rsplit(".", 1)
        expect = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            raise ValueError("capability_invalid")
        data = json.loads(body)
        cap = WorkerCapability(
            UUID(data["o"]),
            UUID(data["t"]),
            UUID(data["r"]),
            int(data["e"]),
            frozenset(data["tools"]),
            token,
        )
        if cap.expires_at <= int(time.time()):
            raise ValueError("capability_expired")
        return cap
    except (ValueError, KeyError, TypeError):
        raise ValueError("capability_invalid") from None


def intersect_scopes(*scope_sets: frozenset[str]) -> frozenset[str]:
    """Hak tidak bertambah hanya karena agent membuat subtask."""
    if not scope_sets:
        return frozenset()
    result = scope_sets[0]
    for other in scope_sets[1:]:
        result = result & other
    return result
