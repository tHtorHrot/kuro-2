"""Baseline rute: 1 aktif + <=2 standby, tanpa fallback otomatis (offline)."""

from jarvis.assistant.route_baseline import BASELINE, baseline_status


def test_baseline_shape_is_manual_switch_only():
    assert BASELINE["policy"] == "manual-switch-only"
    assert BASELINE["active"]["model"].endswith(":free")
    assert BASELINE["active"]["provider"]
    assert len(BASELINE["standbys"]) <= 2
    for standby in BASELINE["standbys"]:
        assert standby["model"].endswith(":free")
        assert standby["provider"] is None  # diverifikasi saat aktivasi, bukan sekarang


def test_live_plan_compared_explicitly():
    active_plan = {
        "model": "apodex/apodex-1.1-mini:free",
        "provider": "novita/bf16",
        "pricing_hash": BASELINE["active"]["pricing_hash"],
    }
    assert baseline_status(active_plan) == {
        "on_baseline": True,
        "pricing_drift": False,
        "pinned_at": "2026-10-11",
    }
    drifted = dict(active_plan, pricing_hash="0" * 64)
    assert baseline_status(drifted)["pricing_drift"] is True
    standby_plan = {"model": "google/gemma-4-31b-it:free", "provider": "other/tag"}
    out = baseline_status(standby_plan)
    assert out == {"on_baseline": False, "known_standby": True, "policy": "manual-switch-only"}
    assert baseline_status({"model": "x/y", "provider": "z"})["known_standby"] is False
