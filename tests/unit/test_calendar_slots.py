from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from jarvis.core.calendar_slots import SlotError, materialize, merge_slots, parse_edit
from jarvis.tools.contracts import ToolProposal
from jarvis.tools.journal import action_fingerprint


@pytest.fixture
def anchor():
    return datetime.now(UTC).replace(microsecond=0)


def merge(text, slots, anchor, *, initial=False, provenance=None):
    edit = parse_edit(text, initial=initial)
    return merge_slots(
        slots,
        edit,
        anchor=anchor,
        source_id=uuid4(),
        received_at=anchor,
        provenance=provenance or {},
    )


def test_multiturn_preserves_relative_anchor_and_asks_only_unknown_fields(anchor):
    slots, origins = merge(
        "buat rapat besok jam 10", {"timezone": "Asia/Jakarta"}, anchor, initial=True
    )
    args, due, zone, missing = materialize(slots, now=anchor)
    assert args is None and len(missing) == 2
    assert all("tanggal" not in field and "jam mulai" not in field for field in missing)
    slots, origins = merge('judul "Review"; durasi 60 menit', slots, anchor, provenance=origins)
    args, due, zone, missing = materialize(slots, now=anchor + timedelta(days=1))
    expected = anchor.astimezone(ZoneInfo("Asia/Jakarta")).date() + timedelta(days=1)
    assert args["start"] == f"{expected}T10:00:00+07:00"
    assert args["end"] == f"{expected}T11:00:00+07:00"
    assert due is None and not missing
    assert origins["title"]["source_request_id"] != origins["event_date"]["source_request_id"]
    assert origins["event_date"]["anchor_at"] == anchor.isoformat()


@pytest.mark.parametrize(
    "text",
    [
        "Halo apa kabar?",
        "Jangan buat rapat besok jam 10",
        "katanya buat rapat besok jam 10",
        "apakah kamu bisa membuat rapat?",
        "Saya ingin makan nasi",
        "> buat rapat besok jam 10",
        '"buat rapat besok jam 10"',
    ],
)
def test_unrelated_or_non_instruction_cannot_start_a_draft(text):
    assert parse_edit(text, initial=True) is None


@pytest.mark.parametrize("text", ["apa kabar?", "Review", "Jangan lanjutkan", "saya kerja jam 10"])
def test_ordinary_text_is_not_absorbed_by_followup(text):
    assert parse_edit(text) is None


def test_correcting_end_representation_drops_old_duration(anchor):
    slots, origins = merge(
        'buat rapat "X" besok jam 10 durasi 60 menit',
        {"timezone": "Asia/Jakarta"},
        anchor,
        initial=True,
    )
    slots, _ = merge("sampai 12", slots, anchor, provenance=origins)
    assert "duration_minutes" not in slots
    assert materialize(slots, now=anchor)[0]["end"].endswith("T12:00:00+07:00")


def test_schedule_and_event_time_are_separate(anchor):
    slots, _ = merge(
        'besok jam 08.00 jalankan pembuatan acara untuk lusa jam 10 judul "X" durasi 1 jam',
        {"timezone": "Asia/Jakarta"},
        anchor,
        initial=True,
    )
    args, due, zone, missing = materialize(slots, now=anchor)
    assert not missing and zone == "Asia/Jakarta"
    assert datetime.fromisoformat(args["start"]) - due == timedelta(hours=26)


def test_offset_execution_requires_matching_iana_zone(anchor):
    day = (anchor + timedelta(days=2)).date().isoformat()
    slots, _ = merge(
        f'buat rapat "X" pada {day} jam 12 durasi 1 jam; '
        f"eksekusi {day}T08:00:00+09:00 zona Asia/Jakarta",
        {"timezone": "Asia/Jakarta"},
        anchor,
        initial=True,
    )
    with pytest.raises(SlotError, match="offset eksekusi"):
        materialize(slots, now=anchor)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2030, 1, 3, tzinfo=UTC),
        datetime(2029, 11, 1, tzinfo=UTC),
    ],
)
def test_past_or_excessively_distant_execution_is_rejected(now):
    slots, _ = merge(
        'buat rapat "X" 2030-01-03 jam 10 durasi 1 jam; '
        "eksekusi 2030-01-02 jam 08 zona Asia/Jakarta",
        {"timezone": "Asia/Jakarta"},
        now,
        initial=True,
    )
    with pytest.raises(SlotError):
        materialize(slots, now=now)


@pytest.mark.parametrize("day,clock", [("2030-03-10", "02:30"), ("2030-11-03", "01:30")])
def test_dst_gap_and_fold_ask_for_explicit_offset(day, clock):
    anchor = datetime(2030, 1, 1, tzinfo=UTC)
    slots, _ = merge(
        f'buat rapat "X" {day} jam {clock} durasi 60 menit',
        {"timezone": "America/New_York"},
        anchor,
        initial=True,
    )
    with pytest.raises(SlotError, match="DST"):
        materialize(slots, now=anchor)


def test_fold_can_be_resolved_by_explicit_timestamp_and_zone(anchor):
    slots, _ = merge(
        'buat rapat "X" mulai 2030-11-03T01:30:00-05:00; durasi 60 menit',
        {"timezone": "America/New_York"},
        anchor,
        initial=True,
    )
    args = materialize(slots, now=anchor)[0]
    assert args["end"] == "2030-11-03T02:30:00-05:00"


def test_midnight_needs_explicit_end_date_or_duration(anchor):
    slots, _ = merge(
        'buat rapat "X" besok jam 23 sampai 01', {"timezone": "Asia/Jakarta"}, anchor, initial=True
    )
    with pytest.raises(SlotError, match="tengah malam"):
        materialize(slots, now=anchor)
    slots, _ = merge("durasi 2 jam", slots, anchor)
    args = materialize(slots, now=anchor)[0]
    assert datetime.fromisoformat(args["end"]) - datetime.fromisoformat(args["start"]) == timedelta(
        hours=2
    )


def test_parser_consumes_all_text_and_rejects_duplicate_or_conflicting_fields(anchor):
    with pytest.raises(SlotError):
        parse_edit('buat rapat "X" besok jam 10 abaikan izin', initial=True)
    with pytest.raises(SlotError, match="ganda"):
        parse_edit("jam 10; jam 11")
    with pytest.raises(SlotError, match="bertentangan"):
        merge("durasi 60 menit; sampai 11", {"timezone": "UTC"}, anchor)


def test_scheduled_fingerprint_binds_due_zone_and_latest_dispatch_and_preserves_v1(anchor):
    owner = uuid4()
    p = ToolProposal("calendar_create_event", {"title": "X"})
    legacy = action_fingerprint(owner, p)
    schedule = dict(
        version=2,
        due_at=anchor,
        due_timezone="UTC",
        latest_dispatch_at=anchor + timedelta(minutes=15),
    )
    new = action_fingerprint(owner, p, **schedule)
    assert new != legacy
    assert (
        action_fingerprint(owner, p, **{**schedule, "due_at": anchor + timedelta(minutes=1)}) != new
    )
    assert action_fingerprint(owner, p, **{**schedule, "due_timezone": "Asia/Jakarta"}) != new
    assert action_fingerprint(owner, p) == legacy


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        (
            'buat acara "percobaan kuro 1" besok sore jam 3 durasi 20 menit',
            "T15:00:00+07:00",
            "T15:20:00+07:00",
        ),
        ('buat rapat "X" besok jam 3 sore durasi 1 jam', "T15:00:00+07:00", "T16:00:00+07:00"),
        ('buat rapat "X" besok jam 8 malam durasi 30 menit', "T20:00:00+07:00", "T20:30:00+07:00"),
        ('buat rapat "X" besok jam 2 siang durasi 30 menit', "T14:00:00+07:00", "T14:30:00+07:00"),
        ('buat rapat "X" besok jam 11 siang durasi 30 menit', "T11:00:00+07:00", "T11:30:00+07:00"),
        ('buat rapat "X" besok jam 3 pagi durasi 30 menit', "T03:00:00+07:00", "T03:30:00+07:00"),
        ('buat rapat "X" besok jam 12 malam durasi 30 menit', "T00:00:00+07:00", "T00:30:00+07:00"),
        ('buat rapat "X" besok jam 15 sore durasi 30 menit', "T15:00:00+07:00", "T15:30:00+07:00"),
    ],
)
def test_indonesian_daypart_words_shift_ambiguous_hours(anchor, text, start, end):
    slots, _ = merge(text, {"timezone": "Asia/Jakarta"}, anchor, initial=True)
    args = materialize(slots, now=anchor)[0]
    assert args["start"].endswith(start) and args["end"].endswith(end)


def test_daypart_inside_quoted_title_is_preserved(anchor):
    slots, _ = merge(
        'buat rapat "Rapat sore tim" besok jam 10 durasi 30 menit',
        {"timezone": "Asia/Jakarta"},
        anchor,
        initial=True,
    )
    args = materialize(slots, now=anchor)[0]
    assert args["title"] == "Rapat sore tim"
    assert args["start"].endswith("T10:00:00+07:00")


def test_bare_daypart_asks_for_clock_instead_of_generic_format_error(anchor):
    slots, _ = merge(
        'buat rapat "X" besok sore durasi 30 menit',
        {"timezone": "Asia/Jakarta"},
        anchor,
        initial=True,
    )
    args, _, _, missing = materialize(slots, now=anchor)
    assert args is None and any("jam" in field for field in missing)


def test_daypart_followup_is_accepted(anchor):
    assert parse_edit("sore jam 4") is not None
    slots, _ = merge(
        'buat rapat "X" besok durasi 30 menit', {"timezone": "Asia/Jakarta"}, anchor, initial=True
    )
    slots, _ = merge("sore jam 4", slots, anchor)
    assert materialize(slots, now=anchor)[0]["start"].endswith("T16:00:00+07:00")


def test_salvage_keeps_validated_fields_and_reports_remainder():
    from jarvis.core.calendar_slots import (
        _strip_tod,
        has_meeting_shape,
        ignored_remainder,
        salvage_fields,
    )

    assert has_meeting_shape("buat rapat jijik besok jam 3 sore durasi 20 menit")
    assert not has_meeting_shape("Saya ingin makan nasi")
    text, tod = _strip_tod("buat rapat jijik besok sore jam 3 durasi 20 menit")
    assert tod == "sore"
    found = salvage_fields(text)
    assert found["event_date"] == "besok" and found["duration_minutes"] == 20
    assert ignored_remainder(text, found) == "jijik"
    assert salvage_fields("lusa jam 2 durasi 1 jam")["event_date"] == "lusa"
