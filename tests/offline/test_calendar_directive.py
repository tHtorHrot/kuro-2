import unittest

from jarvis.core.calendar_directive import matches_solo_create

TEXT = 'KURO, buat rapat "Review" pada 2026-10-03 jam 10:00 sampai 11:00 zona Asia/Jakarta'
ARGS = {
    "title": "Review",
    "start": "2026-10-03T10:00:00+07:00",
    "end": "2026-10-03T11:00:00+07:00",
    "timezone": "Asia/Jakarta",
}


class CalendarDirectiveTests(unittest.TestCase):
    def test_exact_complete_instruction_matches(self):
        self.assertTrue(matches_solo_create(TEXT, ARGS))

    def test_equivalent_utc_instants_match(self):
        args = {**ARGS, "start": "2026-10-03T03:00:00Z", "end": "2026-10-03T04:00:00Z"}
        self.assertTrue(matches_solo_create(TEXT, args))

    def test_negation_question_quotation_and_hedges_do_not_authorize(self):
        for value in [
            "Jangan " + TEXT,
            "Bagaimana cara " + TEXT,
            "Mungkin " + TEXT,
            "Contoh: " + TEXT,
            f"```{TEXT}```",
            f'"{TEXT}"',
            TEXT + "?",
            TEXT + ". Tapi jangan dijalankan.",
            "KURO, jangan buat rapat besok",
            "KURO, buat rapat besok jam 10",
        ]:
            with self.subTest(value=value):
                self.assertFalse(matches_solo_create(value, ARGS))

    def test_model_cannot_change_title_time_date_or_timezone(self):
        for key, value in [
            ("title", "Other meeting"),
            ("start", "2026-10-03T12:00:00+07:00"),
            ("end", "2026-10-03T12:00:00+07:00"),
            ("timezone", "Asia/Makassar"),
            ("start", "2026-10-04T10:00:00+07:00"),
        ]:
            with self.subTest(key=key):
                self.assertFalse(matches_solo_create(TEXT, {**ARGS, key: value}))

    def test_attendees_or_authority_fields_are_not_solo_create(self):
        for key, value in [("attendees", ["a@example.com"]), ("authorized", True)]:
            with self.subTest(key=key):
                self.assertFalse(matches_solo_create(TEXT, {**ARGS, key: value}))

    def test_naive_or_invalid_timestamps_are_not_accepted(self):
        for value in ["2026-10-03T10:00:00", "bad", "2026-02-30T10:00:00Z", 123, None]:
            with self.subTest(value=value):
                self.assertFalse(matches_solo_create(TEXT, {**ARGS, "start": value}))

    def test_invalid_or_reversed_local_time_is_not_accepted(self):
        for old, new in [
            ("2026-10-03", "2026-02-30"),
            ("11:00", "09:00"),
            ("10:00", "25:00"),
            ("Asia/Jakarta", "Mars/Olympus"),
        ]:
            with self.subTest(new=new):
                self.assertFalse(matches_solo_create(TEXT.replace(old, new), ARGS))

    def test_dst_gap_and_fold_require_clarification(self):
        for day, start, end, offset in [
            ("2026-03-08", "02:30", "03:30", "-05:00"),
            ("2026-11-01", "01:30", "02:30", "-04:00"),
        ]:
            with self.subTest(day=day):
                text = (
                    f'buat acara "Review" pada {day} jam {start} sampai {end} zona America/New_York'
                )
                args = {
                    "title": "Review",
                    "start": f"{day}T{start}:00{offset}",
                    "end": f"{day}T{end}:00{offset}",
                    "timezone": "America/New_York",
                }
                self.assertFalse(matches_solo_create(text, args))

    def test_no_substring_match_across_multiple_actions(self):
        self.assertFalse(matches_solo_create(TEXT + " dan undang Andi", ARGS))

    def test_arbitrary_objects_are_rejected(self):
        for text, args in [(None, ARGS), (TEXT, []), (TEXT, {}), (TEXT, {**ARGS, "title": []})]:
            with self.subTest(text=text, kind=type(args).__name__):
                self.assertFalse(matches_solo_create(text, args))
