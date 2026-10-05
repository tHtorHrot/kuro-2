from copy import deepcopy

import pytest

from jarvis.assistant.repository import telegram_text
from jarvis.orchestration.calendar_display import format_calendar_events


def event(start="2026-10-05T02:00:00Z", end="2026-10-05T03:00:00Z", title="Rapat tim"):
    return {
        "id": "private-provider-id",
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }


def agenda(events, **kwargs):
    return format_calendar_events(
        events,
        time_min="2026-10-05T00:00:00+07:00",
        timezone=kwargs.get("timezone", "Asia/Jakarta"),
    )


@pytest.mark.parametrize(
    ("zone", "label", "hours"),
    [
        ("Asia/Jakarta", "WIB", "09.00–10.00"),
        ("Asia/Pontianak", "WIB", "09.00–10.00"),
        ("Asia/Makassar", "WITA", "10.00–11.00"),
        ("Asia/Jayapura", "WIT", "11.00–12.00"),
    ],
)
def test_converts_provider_offset_to_owner_zone_and_preserves_journal_data(zone, label, hours):
    events = [event()]
    original = deepcopy(events)
    text = agenda(events, timezone=zone)
    assert f"Jadwal Senin, 5 Oktober 2026 ({label})" in text
    assert f"• {hours} — Rapat tim" in text
    assert "private-provider-id" not in text and "dateTime" not in text
    assert events == original


def test_all_day_and_exclusive_multi_day_end_dates():
    text = agenda(
        [
            {"summary": "Cuti", "start": {"date": "2026-10-05"}, "end": {"date": "2026-10-06"}},
            {"summary": "Liburan", "start": {"date": "2026-10-04"}, "end": {"date": "2026-10-07"}},
        ]
    )
    assert "• Sepanjang hari — Cuti" in text
    assert "Sepanjang hari (4 Oktober 2026–6 Oktober 2026) — Liburan" in text
    assert "7 Oktober" not in text


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2026-10-05T23:30:00+07:00", "2026-10-06T01:00:00+07:00", "23.30–6 Oktober 2026 01.00"),
        ("2026-10-04T23:30:00+07:00", "2026-10-05T01:00:00+07:00", "4 Oktober 2026 23.30–01.00"),
    ],
)
def test_overnight_events_do_not_appear_to_end_before_start(start, end, expected):
    assert expected in agenda([event(start, end)])


def test_dst_clock_repetition_has_distinct_utc_offsets():
    text = format_calendar_events(
        [event("2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00")],
        time_min="2026-11-01T00:00:00-04:00",
        timezone="America/New_York",
    )
    assert "01.30 (UTC-0400)–01.30 (UTC-0500)" in text


def test_incomplete_event_does_not_block_delivery_or_guess_a_time():
    text = agenda(
        [
            {"id": "a", "summary": "  "},
            event(start="2026-10-05T09:00:00", title="No offset"),
            event(end="invalid", title="Review\n\tproyek"),
        ]
    )
    assert "Waktu belum tersedia — (tanpa judul)" in text
    assert "Waktu belum tersedia — No offset" in text
    assert "09.00 (selesai belum tersedia) — Review proyek" in text
    assert text.count("\n• ") == 3


def test_empty_day_keeps_requested_date():
    assert agenda([]) == "Jadwal Senin, 5 Oktober 2026 (WIB)\n\nTidak ada acara."


def test_busy_agenda_is_bounded_on_whole_events_and_reports_hidden_count():
    events = [event(title="📅" * 200) for _ in range(100)]
    text = agenda(events)
    displayed = text.count("\n• ")
    assert 0 < displayed < 100
    assert f"… {100 - displayed} acara lainnya." in text
    assert text == telegram_text(text)
    assert len(text.encode("utf-16-le")) <= 7600


def test_invalid_legacy_timezone_is_explicitly_displayed_as_utc():
    text = agenda([event()], timezone="invalid/zone")
    assert "(UTC)" in text and "5 Oktober 2026 02.00" in text
