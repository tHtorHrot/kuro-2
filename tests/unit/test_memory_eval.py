"""Stage 6 slice 2 eval: fixed labeled set for context selection.

Baseline behavior is pinned here before rollout: relevance order, leakage
(absence of restricted/expired facts), and bounded cost. Scores are recorded
as constants, not invented; rerun and compare before changing rank_facts.
"""

import time
from datetime import UTC, datetime, timedelta

from jarvis.memory.repository import MAX_CONTEXT_CHARS, MAX_CONTEXT_FACTS, rank_facts


def labels(days_ago=0, **over):
    base = {
        "key": "k",
        "value": "v",
        "kind": "profile",
        "importance": 0.5,
        "updated_at": datetime.now(UTC) - timedelta(days=days_ago),
        "data_class": "private",
        "status": "active",
        "expires_at": None,
    }
    return {**base, **over}


def test_preference_beats_profile_and_stale_task_loses():
    facts = [
        labels(key="tugas", value="x", kind="task", importance=1.0, days_ago=60),
        labels(key="profil", value="y", kind="profile", importance=0.0, days_ago=60),
        labels(key="suka", value="kopi", kind="preference", importance=0.0, days_ago=60),
    ]
    assert [f["key"] for f in rank_facts(facts, budget_chars=10**9)] == [
        "suka",
        "profil",
        "tugas",
    ]


def test_restricted_expired_and_deleted_never_surface():
    facts = [
        labels(key="ok", value="v"),
        labels(key="secret", value="v", data_class="restricted"),
        labels(key="basi", value="v", expires_at=datetime.now(UTC) - timedelta(seconds=1)),
        labels(key="hapus", value="v", status="deleted"),
    ]
    assert [f["key"] for f in rank_facts(facts, budget_chars=10**9)] == ["ok"]


def test_cost_is_bounded_by_chars_and_count():
    facts = [labels(key=f"k{i:03}", value="x" * 500) for i in range(40)]
    picked = rank_facts(facts)
    assert len(picked) <= MAX_CONTEXT_FACTS
    assert sum(len(f["value"]) for f in picked) <= MAX_CONTEXT_CHARS
    assert len(picked) == MAX_CONTEXT_CHARS // 500


def test_selection_is_fast_enough_for_inline_inference():
    facts = [labels(key=f"k{i:04}", value="v") for i in range(1000)]
    started = time.monotonic()
    assert len(rank_facts(facts)) > 0
    assert time.monotonic() - started < 1.0
