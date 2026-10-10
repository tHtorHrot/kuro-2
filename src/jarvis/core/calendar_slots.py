"""Bounded, fully consumed Calendar grammar. Slots are proposals, never authority."""

import re
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.core.calendar_directive import _local_time
from jarvis.integrations.calendar.validation import timestamp, validate_arguments

DAY = r"(?:hari ini|besok|lusa|\d{4}-\d{2}-\d{2})"
CLOCK = r"(?:[01]?\d|2[0-3])(?:[:.][0-5]\d)?"
STAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})"
ZONE = r"[A-Za-z0-9_+\-/]{1,64}"
DRAFT_TTL = timedelta(minutes=30)
MAX_OPEN_DRAFTS = 3
MAX_PENDING_JOBS = 25
MAX_TURNS = 20
MAX_FUTURE = timedelta(days=30)
LATE_WINDOW = timedelta(minutes=15)


class SlotError(ValueError):
    """Safe local code; caller asks for an explicit correction."""


# Penanda waktu harian Indonesia. Hanya dikenali di luar judul berquote.
TOD = r"(?:pagi|siang|sore|malam|dini\s*hari|subuh|tengah\s*malam)"


def _strip_tod(raw: str) -> tuple[str, str | None]:
    """Ambil satu penanda waktu di luar quote; kembalikan sisa teks dan katanya."""
    parts = re.split(r'("[^"\r\n]*")', raw)
    for i in range(0, len(parts), 2):
        found = re.search(r"\b" + TOD + r"\b", parts[i], re.I)
        if found:
            word = re.sub(r"\s+", " ", found[0].lower())
            parts[i] = parts[i][: found.start()] + " " + parts[i][found.end() :]
            cleaned = re.sub(r"[ \t]+", " ", "".join(parts)).strip(" ,;")
            return re.sub(r"\s+([,;])", r"\1", cleaned), word
    return raw, None


def _apply_tod(clock: str, word: str) -> str:
    """Jam 1–11 + penanda menjadi 24 jam. Jam 12+ eksplisit selalu menang."""
    hour, _, minute = clock.partition(":")
    hour = int(hour)
    if hour == 12 and word == "malam":
        return f"00:{minute or '00'}"
    if hour > 11:
        return clock
    if word == "siang":
        hour = hour + 12 if hour <= 10 else hour
    elif word == "sore":
        hour = hour + 12 if hour <= 6 else hour
    elif word == "malam":
        if hour == 12:
            hour = 0
        elif 4 <= hour <= 11:
            hour += 12
    return f"{hour:02}:{minute or '00'}"


@dataclass(frozen=True)
class SlotEdit:
    fields: dict
    initial: bool = False
    target: str | None = None
    short_clock: bool = False


def _zone(value):
    try:
        return ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise SlotError("zona IANA tidak valid") from None


def _day(value, anchor, timezone):
    key = value.lower()
    offsets = {"hari ini": 0, "besok": 1, "lusa": 2}
    try:
        return (
            anchor.astimezone(_zone(timezone)).date() + timedelta(days=offsets[key])
            if key in offsets
            else date.fromisoformat(value)
        ).isoformat()
    except ValueError:
        raise SlotError("tanggal tidak valid") from None


def _clock(value):
    parts = re.split(r"[:.]", value)
    return f"{int(parts[0]):02}:{int(parts[1]) if len(parts) > 1 else 0:02}"


def parse_edit(text: str, *, initial=False) -> SlotEdit | None:
    """No arbitrary bare text becomes a title; followups use labels or quoted title."""
    raw = text.strip()
    target = None
    ref = re.match(r"draft\s+([0-9a-fA-F-]{36})\s*:\s*", raw, re.I)
    if ref:
        try:
            target = str(UUID(ref[1]))
        except ValueError:
            raise SlotError("ID draft tidak valid") from None
        raw = raw[ref.end() :]
    raw, tod = _strip_tod(raw)
    fields = {}
    short_clock = False
    if initial:
        scheduled = re.fullmatch(
            rf"({DAY})\s+jam\s+({CLOCK})\s+jalankan\s+pembuatan\s+"
            r"(?:acara|rapat|meeting|event)\s+untuk\s+(.+)",
            raw,
            re.I,
        )
        if scheduled:
            fields.update(execute_date=scheduled[1], execute_clock=_clock(scheduled[2]))
            raw = scheduled[3]
        else:
            start = re.match(
                rf"(?:KURO[, :]\s*)?(?:tolong\s+)?{VERB}\s+{MEETING_NOUN}\b\s*",
                raw,
                re.I,
            )
            if not start:
                # No verb: only a leading meeting noun + temporal signal may start
                # a draft. Anything quoted, negated or hearsay stays out, and the
                # user still confirms before anything executes.
                bare_leading = re.match(rf"(?:KURO[, :]\s*)?{MEETING_NOUN}\b\s*", raw, re.I)
                if not bare_leading:
                    return None
                bare = _unquoted(raw)
                if re.search(rf"\b{NEGATION}\b", bare, re.I):
                    return None
                if not re.search(rf"(?:{DAY}|{CLOCK}|\bdurasi\b|\bjam\b|\btanggal\b)", bare, re.I):
                    return None
                raw = raw[bare_leading.end() :]
            else:
                raw = raw[start.end() :]
    elif not ref and not re.match(
        rf'(?:judul\b|"|tanggal\b|jam\b|sampai\b|hingga\b|durasi\b|zona\b|'
        rf"mulai\b|selesai\b|eksekusi\b|pagi\b|siang\b|sore\b|malam\b|"
        rf"dini\b|subuh\b|tengah\b|{DAY}$|{CLOCK}$)",
        raw,
        re.I,
    ):
        return None
    fields, short_clock = _consume_fields(raw, fields, tod)
    return SlotEdit(fields, initial, target, short_clock)


VERB = r"(?:buat(?:kan)?|bikin|tambahkan|jadwalkan)"
MEETING_NOUN = r"(?:rapat|meeting|acara|event)"
NEGATION = r"(?:jangan|tidak|nggak|gak|tanpa)"

FIELD_PATTERNS = (
    (rf"eksekusi\s+({STAMP})\s+zona\s+({ZONE})", "execute_timestamp"),
    (
        rf"eksekusi\s+(?:pada\s+)?({DAY})\s+jam\s+({CLOCK})"
        rf"(?:\s+zona\s+({ZONE}))?",
        "execute_date",
    ),
    (rf"tanggal\s+akhir\s*[:=]?\s*({DAY})", "end_date"),
    (rf"(?:tanggal\s*[:=]?\s*|pada\s+|untuk\s+)?({DAY})", "event_date"),
    (rf"mulai\s+({STAMP})", "start_timestamp"),
    (rf"selesai\s+({STAMP})", "end_timestamp"),
    (rf"(?:jam|mulai)\s*[:=]?\s*({CLOCK})", "start_clock"),
    (rf"(?:sampai|hingga)\s+(?:jam\s+)?({CLOCK})", "end_clock"),
    (r"durasi\s*[:=]?\s*(\d{1,4})\s+(menit|jam)", "duration_minutes"),
    (rf"zona\s*[:=]?\s*({ZONE})", "timezone"),
    (r'(?:judul\s*[:=]?\s*)?"([^"\r\n]{1,200})"', "title"),
    (
        r"judul\s*[:=]?\s*([^;,\r\n]{1,200}?)(?=\s+(?:durasi|jam|zona|"
        r"tanggal|eksekusi|sampai|hingga)\b|[;,]|$)",
        "title",
    ),
)


def _unquoted(raw: str) -> str:
    """Text outside double-quoted titles; quoted words never steer parsing."""
    return re.sub(r'"[^"\r\n]*"', " ", raw)


def has_meeting_shape(raw: str) -> bool:
    """Verb + meeting noun outside quotes (strict gate for salvage and drafts)."""
    bare = _unquoted(raw)
    return (
        re.search(rf"\b{VERB}\b", bare, re.I) is not None
        and re.search(rf"\b{MEETING_NOUN}\b", bare, re.I) is not None
    )


def salvage_fields(raw: str) -> dict:
    """Best-effort validated fields from a message the strict parser rejected.

    Only quoted titles are trusted; bare words are never guessed as titles.
    Raises SlotError when nothing recognizable remains.
    """
    found: dict = {}
    for pattern, key in FIELD_PATTERNS:
        if key in found or key in {
            "execute_timestamp",
            "execute_date",
            "start_timestamp",
            "end_timestamp",
        }:
            continue
        match = re.search(pattern, raw, re.I)
        if not match:
            continue
        value = match[1].strip()
        if key in {"start_clock", "end_clock"}:
            value = _clock(value)
        elif key == "duration_minutes":
            value = int(value) * (60 if match[2].lower() == "jam" else 1)
            if not 1 <= value <= 7 * 24 * 60:
                continue
        elif key == "timezone":
            try:
                _zone(value)
            except SlotError:
                continue
        found[key] = value
    temporal = {"event_date", "start_clock", "duration_minutes", "end_clock"} & set(found)
    if not temporal:
        raise SlotError("tidak ada tanggal/jam/durasi yang dikenali")
    return found


def ignored_remainder(raw: str, known: dict) -> str | None:
    """Leftover words worth reporting, e.g. 'sama Budi'. None when clean."""
    rest = raw
    for pattern, _ in FIELD_PATTERNS:
        rest = re.sub(pattern, " ", rest, flags=re.I)
    rest = re.sub(rf"\b{VERB}\b|\b{MEETING_NOUN}\b|{TOD}", " ", rest, flags=re.I)
    rest = re.sub(r"[\"',;:.]+", " ", rest).split()
    keep = [w for w in rest if len(w) > 2]
    if not keep:
        return None
    return " ".join(keep[:8])


def _consume_fields(raw: str, fields: dict, tod: str | None) -> tuple[dict, bool]:
    short_clock = False

    def put(key, value):
        if key in fields:
            raise SlotError("field ganda; kirim satu nilai per field")
        fields[key] = value

    while raw.strip(" ,;"):
        raw = raw.lstrip(" ,;")
        for pattern, key in FIELD_PATTERNS:
            m = re.match(pattern + r"(?=$|[\s,;])", raw, re.I)
            if not m:
                continue
            value = m[1].strip()
            if key in {"start_clock", "end_clock"}:
                value = _clock(value)
            elif key == "duration_minutes":
                value = int(value) * (60 if m[2].lower() == "jam" else 1)
                if not 1 <= value <= 7 * 24 * 60:
                    raise SlotError("durasi harus 1 menit sampai 7 hari")
            elif key in {"timezone", "execute_timestamp"}:
                _zone(m[2] if key == "execute_timestamp" else value)
            if key == "execute_date":
                put("execute_clock", _clock(m[2]))
                if m[3]:
                    _zone(m[3])
                    put("execute_timezone", m[3])
            if key == "execute_timestamp":
                timestamp(value)
                put("execute_timezone", m[2])
            if key == "title" and (not value or any(ord(c) < 32 for c in value)):
                raise SlotError("judul tidak valid")
            put(key, value)
            raw = raw[m.end() :]
            break
        else:
            # An isolated clock is a relevant short answer, not general prose.
            if re.fullmatch(CLOCK, raw):
                short_clock = True
                put("start_clock", _clock(raw))
                raw = ""
            else:
                raise SlotError(
                    'format belum jelas; gunakan judul "..."; durasi 60 menit; '
                    "tanggal YYYY-MM-DD; jam HH:MM; atau eksekusi TANGGAL jam HH:MM"
                )
    if tod:
        for key in ("start_clock", "end_clock", "execute_clock"):
            if key in fields:
                fields[key] = _apply_tod(fields[key], tod)
    return fields, short_clock


def merge_slots(slots, edit, *, anchor, source_id, received_at, provenance):
    """Relative dates always refer to the saved task anchor, including later corrections."""
    fields, origins = dict(slots), dict(provenance)
    patch = dict(edit.fields)
    timezone = patch.get("timezone", fields.get("timezone"))
    _zone(timezone)
    execute_zone = patch.get("execute_timezone", fields.get("execute_timezone", timezone))
    for key in ("event_date", "end_date", "execute_date"):
        if key in patch:
            patch[key] = _day(
                patch[key], anchor, execute_zone if key == "execute_date" else timezone
            )
    # A correction selects a representation; competing old representations cannot survive.
    groups = (
        ("duration_minutes", ("end_clock", "end_date", "end_timestamp")),
        ("end_clock", ("duration_minutes", "end_timestamp")),
        ("end_timestamp", ("duration_minutes", "end_clock", "end_date")),
        ("start_timestamp", ("start_clock", "event_date")),
        ("start_clock", ("start_timestamp",)),
        ("event_date", ("start_timestamp",)),
        ("execute_timestamp", ("execute_date", "execute_clock")),
        ("execute_date", ("execute_timestamp",)),
    )
    for chosen, replaced in groups:
        if chosen in patch:
            if any(k in patch for k in replaced):
                raise SlotError("dua representasi waktu bertentangan; pilih satu")
            for key in replaced:
                fields.pop(key, None)
                origins.pop(key, None)
    for key, value in patch.items():
        fields[key] = value
        origins[key] = {
            "source_request_id": str(source_id),
            "received_at": received_at.isoformat(),
            "anchor_at": anchor.isoformat(),
            "value": value,
            "raw_value": edit.fields[key],
        }
    if len({v.get("source_request_id") for v in origins.values()}) > MAX_TURNS:
        raise SlotError("batas turn draft tercapai; mulai draft baru")
    return fields, origins


def materialize(slots, *, now):
    """Return exact args/schedule or only missing fields. Never infer title/end/duration."""
    missing = []
    if "title" not in slots:
        missing.append('judul (jawab: judul "Review")')
    if "start_timestamp" not in slots:
        if "event_date" not in slots:
            missing.append("tanggal acara")
        if "start_clock" not in slots:
            missing.append("jam mulai")
    if not {"duration_minutes", "end_clock", "end_timestamp"}.intersection(slots):
        missing.append("durasi/jam selesai (jawab: durasi 60 menit)")
    has_schedule = any(k.startswith("execute_") and k != "execute_timezone" for k in slots)
    if has_schedule and "execute_timestamp" not in slots:
        if "execute_date" not in slots:
            missing.append("tanggal eksekusi")
        if "execute_clock" not in slots:
            missing.append("jam eksekusi")
    if missing:
        return None, None, None, missing
    zone = _zone(slots["timezone"])
    try:
        start = (
            timestamp(slots["start_timestamp"])
            if "start_timestamp" in slots
            else _local_time(slots["event_date"], slots["start_clock"], zone)
        )
        if "end_timestamp" in slots:
            end = timestamp(slots["end_timestamp"])
        elif "duration_minutes" in slots:
            end = (start.astimezone(UTC) + timedelta(minutes=slots["duration_minutes"])).astimezone(
                zone
            )
        else:
            end = _local_time(
                slots.get(
                    "end_date", slots.get("event_date", start.astimezone(zone).date().isoformat())
                ),
                slots["end_clock"],
                zone,
            )
            if end <= start:
                raise SlotError("jam akhir lintas tengah malam perlu tanggal akhir atau durasi")
        args = {
            "title": slots["title"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": slots["timezone"],
        }
        validate_arguments("calendar_create_event", args)
        due = None
        due_zone = slots.get("execute_timezone", slots["timezone"])
        if has_schedule:
            execution_zone = _zone(due_zone)
            due = (
                timestamp(slots["execute_timestamp"])
                if "execute_timestamp" in slots
                else _local_time(slots["execute_date"], slots["execute_clock"], execution_zone)
            )
            if due.utcoffset() != due.astimezone(execution_zone).utcoffset():
                raise SlotError("offset eksekusi tidak cocok dengan zona IANA")
            if due <= now:
                raise SlotError("waktu eksekusi sudah lampau; tentukan waktu baru")
            if due.astimezone(UTC) - now.astimezone(UTC) > MAX_FUTURE:
                raise SlotError("eksekusi dibatasi 30 hari ke depan")
            if due >= start:
                raise SlotError("eksekusi harus sebelum acara mulai")
        return args, due, due_zone, []
    except SlotError:
        raise
    except (ValueError, KeyError, OverflowError):
        raise SlotError(
            "waktu/zona ambigu atau tidak valid; untuk DST gunakan mulai/selesai "
            "YYYY-MM-DDTHH:MM:SS±HH:MM dan zona IANA"
        ) from None
