"""Real pure-boundary checks; runnable without pytest or service dependencies.

Run from the project root:
    PYTHONPATH=src python -m unittest discover -s tests/offline -v
These do not replace PostgreSQL, provider, worker, or Docker integration tests.
"""

import unittest
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from jarvis.assistant.commands import INFERENCE_COMMANDS, SLASH_COMMANDS
from jarvis.assistant.policy import safe_content
from jarvis.interfaces.telegram.commands import REPLIES, parse_update

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
CONFIG = SimpleNamespace(sender_id=123456)


def update(text):
    return {
        "update_id": 100,
        "message": {
            "date": int(NOW.timestamp()),
            "from": {"id": CONFIG.sender_id, "is_bot": False},
            "chat": {"id": CONFIG.sender_id, "type": "private"},
            "text": text,
        },
    }


def parse(text):
    return parse_update(update(text), CONFIG, "KuroBot", NOW)


class NaturalIngressTests(unittest.TestCase):
    def test_plain_text_uses_chat(self):
        result = parse("  Halo KURO\nBalas singkat.  ")
        self.assertEqual(result.command, "chat")
        self.assertEqual(result.argument, "Halo KURO\nBalas singkat.")

    def test_email_and_mentions_are_text_not_command_suffixes(self):
        for value in ["andi@example.com siapa ini?", "@Andi halo", "@KuroBot halo"]:
            with self.subTest(value=value):
                result = parse(value)
                self.assertIsNotNone(result)
                self.assertEqual(result.argument, value)
                self.assertEqual(result.command, "chat")

    def test_supported_slash_commands_are_compatible(self):
        for command in SLASH_COMMANDS:
            with self.subTest(command=command):
                self.assertEqual(parse(f"/{command}@KuroBot nilai").command, command)
        self.assertEqual(parse("/ask@KUROBOT Hello").argument, "Hello")

    def test_foreign_commands_and_setup_are_ignored(self):
        for value in ["/ask@OtherBot Halo", "/status@OtherBot", "/jarvis_setup nonce"]:
            with self.subTest(value=value):
                self.assertIsNone(parse(value))

    def test_unknown_commands_do_not_become_chat(self):
        for value in ["/unknown argument", "/chat Halo", "/calendar_create X"]:
            with self.subTest(value=value):
                self.assertEqual(parse(value).command, "unsupported")
                self.assertIsNone(parse(value).argument)

    def test_empty_oversized_and_nontext_do_not_retain_content(self):
        for value in ["", " \n\t", "a" * 4097, None, {"text": "unexpected"}]:
            with self.subTest(kind=type(value).__name__):
                result = parse(value)
                self.assertEqual(result.command, "unsupported")
                self.assertIsNone(result.argument)

    def test_attachment_caption_is_not_a_prompt(self):
        value = update(None)
        value["message"].update(document={"file_id": "private"}, caption="Do this")
        result = parse_update(value, CONFIG, "KuroBot", NOW)
        self.assertEqual(result.command, "unsupported")
        self.assertIsNone(result.argument)

    def test_identity_and_private_chat_checks_also_apply_to_chat(self):
        for field, value in [
            ("from", {"id": 987, "is_bot": False}),
            ("from", {"id": CONFIG.sender_id, "is_bot": True}),
            ("from", {"id": str(CONFIG.sender_id), "is_bot": False}),
            ("chat", {"id": CONFIG.sender_id, "type": "group"}),
            ("chat", {"id": 987, "type": "private"}),
            ("date", int(NOW.timestamp()) - 86401),
            ("date", int(NOW.timestamp()) + 61),
        ]:
            with self.subTest(field=field, value=value):
                row = update("Halo")
                row["message"][field] = value
                self.assertIsNone(parse_update(row, CONFIG, "KuroBot", NOW))

    def test_forwarded_and_delegated_chat_is_rejected(self):
        for field in [
            "forward_origin",
            "forward_from",
            "forward_from_chat",
            "forward_date",
            "via_bot",
            "sender_chat",
            "business_connection_id",
            "sender_business_bot",
            "guest_query_id",
            "guest_bot_caller_user",
            "guest_bot_caller_chat",
        ]:
            with self.subTest(field=field):
                row = update("Halo")
                row["message"][field] = None
                self.assertIsNone(parse_update(row, CONFIG, "KuroBot", NOW))

    def test_edited_chat_is_not_a_new_instruction(self):
        row = update("Halo")
        edited = {"update_id": 100, "edited_message": deepcopy(row["message"])}
        self.assertIsNone(parse_update(edited, CONFIG, "KuroBot", NOW))

    def test_repr_does_not_leak_prompt_or_pair_code(self):
        self.assertNotIn("PRIVATE-PROMPT", repr(parse("PRIVATE-PROMPT")))
        self.assertNotIn("PRIVATE-PAIR", repr(parse("/pair PRIVATE-PAIR")))

    def test_restricted_command_never_copies_payload(self):
        result = parse("/restricted PRIVATE-DOCUMENT")
        self.assertEqual(result.command, "restricted")
        self.assertIsNone(result.argument)

    def test_shared_cloud_filter_rejects_secrets(self):
        for value in ["password=hidden", "api_key: sample", "hello\x00"]:
            with self.subTest(value=value):
                self.assertFalse(safe_content(value))
        self.assertTrue(safe_content("Halo KURO"))
        self.assertEqual(INFERENCE_COMMANDS, frozenset({"ask", "chat"}))

    def test_help_and_privacy_explain_plain_text_cloud_processing(self):
        self.assertIn("Pesan biasa dan /ask", REPLIES["privacy"])
        self.assertIn("pesan biasa", REPLIES["help"])
        self.assertTrue(all(0 < len(v.encode("utf-16-le")) <= 8192 for v in REPLIES.values()))
