"""Knowledge evaluation — citation coverage dan supported claims.

Format check bukan fact verification (K-F06): klaim salah dengan label valid
tetap diterima formatter. Di sini evaluasi evidence per klaim dan abstention.
"""

from __future__ import annotations

from jarvis.orchestration.evaluation import eval_research


def evaluate_answer(*, answer: str, sources: list[dict], supported: int = 0, total: int = 0):
    source_ids = [s.get("label", f"S{i + 1}") for i, s in enumerate(sources)]
    return eval_research(
        answer=answer, source_ids=source_ids, supported_claims=supported, total_claims=total
    )
