import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import SecretStr

Kind = Literal["jvt1", "jvp1"]


@dataclass(frozen=True)
class TokenParts:
    owner_id: UUID
    record_id: UUID


def parse_token(raw: str, kind: Kind = "jvt1") -> TokenParts:
    if len(raw) > 160 or not raw.isascii():
        raise ValueError("Invalid credential format")
    parts = raw.split(".")
    if len(parts) != 4 or parts[0] != kind:
        raise ValueError("Invalid credential format")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", parts[3]):
        raise ValueError("Invalid credential format")
    return TokenParts(UUID(parts[1]), UUID(parts[2]))


def digest(raw: str, pepper: SecretStr) -> bytes:
    return hmac.new(pepper.get_secret_value().encode(), raw.encode(), hashlib.sha256).digest()


def issue_material(owner_id: UUID, pepper: SecretStr, kind: Kind = "jvt1"):
    record_id = uuid4()
    raw = f"{kind}.{owner_id}.{record_id}.{secrets.token_urlsafe(32)}"
    return record_id, SecretStr(raw), digest(raw, pepper)


def matches(raw: str, expected: bytes, pepper: SecretStr) -> bool:
    return hmac.compare_digest(digest(raw, pepper), expected)
