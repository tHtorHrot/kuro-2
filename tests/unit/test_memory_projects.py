"""Stage 6 slice 3: project-scoped context selection (offline, no DB).

S6-02: fakta global selalu ikut; fakta proyek lain tidak pernah bocor;
fakta proyek aktif menang atas global yang setara.
S6-04/S6-05: deleted/expired/restricted tidak pernah surface.
"""

from datetime import UTC, datetime, timedelta

from jarvis.memory.repository import rank_facts


def _fact(key, **over):
    base = {
        "key": key,
        "value": "v",
        "kind": "profile",
        "importance": 0.5,
        "updated_at": datetime.now(UTC),
        "data_class": "private",
        "status": "active",
        "expires_at": None,
        "project": None,
    }
    return {**base, **over}


def test_global_always_competes_other_project_never_surfaces():
    facts = [
        _fact("global", value="g"),
        _fact("milik_a", value="a", project="proyek-a"),
        _fact("milik_b", value="b", project="proyek-b"),
    ]
    picked = rank_facts(facts, budget_chars=10**9, project="proyek-a")
    keys = [f["key"] for f in picked]
    assert "global" in keys
    assert "milik_a" in keys
    assert "milik_b" not in keys


def test_no_active_project_only_global_surfaces():
    facts = [
        _fact("global", value="g"),
        _fact("milik_a", value="a", project="proyek-a"),
    ]
    assert [f["key"] for f in rank_facts(facts, budget_chars=10**9, project=None)] == ["global"]


def test_active_project_outranks_equal_global():
    facts = [
        _fact("global", value="sama"),
        _fact("lokal", value="sama", project="proyek-a"),
    ]
    picked = rank_facts(facts, budget_chars=10**9, project="proyek-a")
    assert [f["key"] for f in picked] == ["lokal", "global"]


def test_deleted_expired_restricted_never_surface_even_in_project():
    facts = [
        _fact("ok", project="proyek-a"),
        _fact("hapus", project="proyek-a", status="deleted"),
        _fact(
            "basi",
            project="proyek-a",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        ),
        _fact("rahasia", project="proyek-a", data_class="restricted"),
        _fact("bocor_lain", project="proyek-b"),
    ]
    assert [f["key"] for f in rank_facts(facts, budget_chars=10**9, project="proyek-a")] == ["ok"]


def test_precedence_weight_still_applies_inside_project():
    facts = [
        _fact("tugas", kind="task", importance=1.0, project="proyek-a"),
        _fact("suka", kind="preference", importance=0.0, project="proyek-a"),
    ]
    # preference (30) mengalahkan task (10) walau importance task maksimal.
    assert [f["key"] for f in rank_facts(facts, budget_chars=10**9, project="proyek-a")] == [
        "suka",
        "tugas",
    ]
