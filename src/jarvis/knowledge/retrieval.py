"""Knowledge retrieval bertahap — multi-document dengan provenance.

Evaluasi retrieval dahulu, kemudian multi-document/hybrid sesuai kebutuhan.
Retrieval dan source freshness terpisah dari authority. Jangan campur tenant.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    source_id: str
    title: str
    locator: str
    text: str


def select_evidence(
    *, query_hits: list[dict], max_docs: int = 3, max_chars: int = 8000
) -> list[Evidence]:
    """Batasi ke beberapa dokumen dengan provenance; potong aman."""
    picked: list[Evidence] = []
    used = 0
    for hit in query_hits[: max_docs * 4]:
        text = (hit.get("text") or "")[:2000]
        if used + len(text) > max_chars:
            break
        picked.append(
            Evidence(
                str(hit.get("source_id", "?")),
                str(hit.get("title", "?")),
                str(hit.get("locator", "?")),
                text,
            )
        )
        used += len(text)
        if len(picked) >= max_docs:
            break
    return picked
