"""Pinned free-route baseline — pelajaran AO #4.

Satu rute AKTIF + maksimal dua STANDBY bernama. Tidak ada fallback
otomatis (manual-switch-only): ganti rute hanya via prosedur aman
(edit config → restart → enable). Router tetap verifikasi live
(ZDR/endpoint/harga) setiap dispatch; baseline di sini niat tercatat,
bukan otoritas.
"""

BASELINE = {
    "pinned_at": "2026-10-11",
    "policy": "manual-switch-only",
    "active": {
        "model": "apodex/apodex-1.1-mini:free",
        "provider": "novita/bf16",
        "verified_at": "2026-10-10T14:52:26+00:00",
        "pricing_hash": "30febc0d186ac02d1163a8cc3c57d96ab9163f86fda9d93b1eb1849248c2a7f3",
        "context_limit": 262144,
    },
    "standbys": [
        {
            "model": "google/gemma-4-31b-it:free",
            "provider": None,
            "model_pricing_zero": True,
            "context_length": 262144,
            "note": "kandidat standby 1 (11 Okt 2026); provider diverifikasi saat aktivasi",
        },
        {
            "model": "nvidia/nemotron-3.5-lightning:free",
            "provider": None,
            "model_pricing_zero": True,
            "context_length": 1000000,
            "note": "kandidat standby 2 (11 Okt 2026); provider diverifikasi saat aktivasi",
        },
    ],
}


def baseline_status(plan: dict) -> dict:
    """Bandingkan plan live vs baseline: aktif / drift / di luar baseline."""
    active = BASELINE["active"]
    if plan.get("model") != active["model"] or plan.get("provider") != active["provider"]:
        known = [s["model"] for s in BASELINE["standbys"]]
        return {
            "on_baseline": False,
            "known_standby": plan.get("model") in known,
            "policy": BASELINE["policy"],
        }
    return {
        "on_baseline": True,
        "pricing_drift": plan.get("pricing_hash") != active["pricing_hash"],
        "pinned_at": BASELINE["pinned_at"],
    }
