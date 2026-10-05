"""Plain-text agenda from committed provider data; no model or authority changes."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
MONTHS = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)
ZONE_LABELS = {
    "Asia/Jakarta": "WIB",
    "Asia/Pontianak": "WIB",
    "Asia/Makassar": "WITA",
    "Asia/Jayapura": "WIT",
}


def _date_label(day):
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def _local_time(raw, zone):
    try:
        value = datetime.fromisoformat(raw)
        # Never guess the server timezone for an incomplete provider timestamp.
        return value.astimezone(zone) if value.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _event_time(event, day, zone):
    start, end = event.get("start") or {}, event.get("end") or {}
    if "date" in start and "dateTime" not in start:
        try:
            first = date.fromisoformat(start["date"])
        except (TypeError, ValueError):
            return "Waktu belum tersedia"
        try:
            # Google all-day end dates are exclusive.
            last = date.fromisoformat(end.get("date", "")) - timedelta(days=1)
        except (TypeError, ValueError, OverflowError):
            last = first
        if last > first:
            return f"Sepanjang hari ({_date_label(first)}–{_date_label(last)})"
        return "Sepanjang hari"

    first = _local_time(start.get("dateTime"), zone)
    last = _local_time(end.get("dateTime"), zone)
    if first is None:
        return "Waktu belum tersedia"

    def clock(value):
        label = value.strftime("%H.%M")
        if value.date() != day:
            label = f"{_date_label(value.date())} {label}"
        if last is not None and first.utcoffset() != last.utcoffset():
            label += f" (UTC{value.strftime('%z')})"
        return label

    if last is None:
        return f"{clock(first)} (selesai belum tersedia)"
    return f"{clock(first)}–{clock(last)}"


def format_calendar_events(events, *, time_min, timezone):
    """Keep event IDs in the journal and bound the reply on complete agenda rows."""
    try:
        zone = ZoneInfo(timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo("UTC")
    requested = _local_time(time_min, zone)
    day = requested.date() if requested else None
    label = ZONE_LABELS.get(zone.key, zone.key)
    heading = (
        f"Jadwal {DAYS[day.weekday()]}, {_date_label(day)} ({label})"
        if day
        else f"Jadwal Google Calendar ({label})"
    )
    if not events:
        return f"{heading}\n\nTidak ada acara."

    text = heading + "\n"
    for index, event in enumerate(events):
        # Calendar titles are plain data, not formatting or additional agenda rows.
        title = " ".join((event.get("summary") or "").split()) or "(tanpa judul)"
        row = f"\n• {_event_time(event, day, zone)} — {title}"
        # Leave room below the existing Telegram UTF-16 guard for a visible notice.
        if len((text + row).encode("utf-16-le")) > 7000:
            remaining = len(events) - index
            return text + f"\n\n… {remaining} acara lainnya. Lihat selengkapnya di Google Calendar."
        text += row
    return text
