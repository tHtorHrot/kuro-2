"""Model routing policy — operator-approved set, tanpa fallback tersembunyi.

Snapshot memakai OpenRouter fixed route, bukan generic router; implementasi
ini menjaga model identity, privacy check, output cap, dan ledger existing.
"""

from __future__ import annotations

from dataclasses import dataclass

OPERATOR_MODELS = {
    "economy": ("kuro-economy-1",),
    "standard": ("kuro-standard-1",),
    "reasoning": ("kuro-reasoning-1",),
}

JOB_TO_CLASS = {
    "parse": None,  # Python deterministik, tidak butuh LLM
    "classify": "economy",
    "summarize": "standard",
    "plan": "reasoning",
    "code": "standard",
}


@dataclass(frozen=True)
class Route:
    model_class: str | None
    model: str | None


def route_job(job: str) -> Route:
    cls = JOB_TO_CLASS.get(job)
    if cls is None:
        return Route(None, None)
    return Route(cls, OPERATOR_MODELS[cls][0])
