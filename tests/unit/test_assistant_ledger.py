"""Stage 2B fix: ledger split is pure and content-free (offline, no DB)."""

from decimal import Decimal

from jarvis.assistant.repository import split_ledger


def test_succeeded_actual_separated_from_held_reservation():
    calls = [
        ("succeeded", Decimal("0.004"), Decimal("0.009")),
        ("dispatching", None, Decimal("0.010")),
        ("uncertain", None, Decimal("0.007")),
        ("rejected", Decimal(0), Decimal("0.005")),
    ]
    out = split_ledger(calls)
    assert out["month_actual_usd"] == "0.004"
    assert out["month_held_usd"] == "0.017"
    assert out["unreconciled"] == 2
    assert out["calls"] == {
        "succeeded": 1,
        "dispatching": 1,
        "uncertain": 1,
        "rejected": 1,
    }


def test_empty_ledger_is_zero_without_error():
    out = split_ledger([])
    assert out["month_actual_usd"] == "0"
    assert out["month_held_usd"] == "0"
    assert out["unreconciled"] == 0
    assert out["calls"] == {}


def test_free_zero_cost_calls_do_not_inflate_spend():
    calls = [("succeeded", Decimal(0), Decimal(0)) for _ in range(3)]
    out = split_ledger(calls)
    assert out["month_actual_usd"] == "0"
    assert out["month_held_usd"] == "0"
    assert out["unreconciled"] == 0
