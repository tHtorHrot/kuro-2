from jarvis.orchestration.calendar_chat import parse_compound, parse_confirmation


def test_bare_words_map_to_single_pending_action():
    assert parse_confirmation("ya") == ("approve", None)
    assert parse_confirmation("Setuju!") == ("approve", None)
    assert parse_confirmation("deal") == ("approve", None)
    assert parse_confirmation("batal") == ("cancel", None)
    assert parse_confirmation("batalin") == ("cancel", None)
    assert parse_confirmation("gak jadi") == ("cancel", None)
    assert parse_confirmation("hapus yang tadi") == ("cancel", None)
    assert parse_confirmation("rapatnya batalin aja") == ("cancel", None)


def test_numbered_replies_map_to_queue_positions():
    assert parse_confirmation("setujui nomor 2") == ("approve", 2)
    assert parse_confirmation("pilih 1") == ("approve", 1)
    assert parse_confirmation("batalkan nomor 1") == ("cancel", 1)
    assert parse_confirmation("nomor 2") == ("show", 2)


def test_non_confirmations_pass_through_to_chat():
    assert parse_confirmation("ya, nanti aku kabari") is None
    assert parse_confirmation("ok") is None
    assert parse_confirmation("12") is None
    assert parse_confirmation("") is None
    assert parse_confirmation("x" * 41) is None
    assert parse_confirmation("hapus semua data") is None


def test_bulk_markers_are_explicit():
    from jarvis.orchestration.calendar_chat import parse_bulk

    assert parse_bulk("batalin semua") == "cancel_all"
    assert parse_bulk("setujui semuanya") == "approve_all"
    assert parse_bulk("setujui nomor 1") is None
    assert parse_bulk("hapus semua data") is None


def test_compound_clauses_execute_in_order_or_not_at_all():
    assert parse_compound("setujui nomor 2 dan batalkan nomor 1") == [
        ("approve", 2),
        ("cancel", 1),
    ]
    assert parse_compound("setujui nomor 1 lalu batalkan nomor 2") == [
        ("approve", 1),
        ("cancel", 2),
    ]
    assert parse_compound("setujui nomor 2 dan hapus semua") is None
    assert parse_compound("setujui nomor 2") is None
    assert parse_compound("ya") is None
