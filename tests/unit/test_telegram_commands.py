from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

import pytest

from jarvis.interfaces.telegram.commands import REPLIES, parse_update
from jarvis.interfaces.telegram.config import TelegramConfig

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
CONFIG = TelegramConfig(owner_id=UUID(int=1), sender_id=123456, bot_id=987654)


def update(text="/status", update_id=100):
    return {
        "update_id": update_id,
        "message": {
            "date": int(NOW.timestamp()),
            "from": {"id": CONFIG.sender_id, "is_bot": False},
            "chat": {"id": CONFIG.sender_id, "type": "private"},
            "text": text,
        },
    }


@pytest.mark.parametrize("command", ["start", "help", "status", "privacy", "pair"])
def test_own_private_commands(command):
    parsed = parse_update(update("/" + command + "@MyJarvisBot"), CONFIG, "myjarvisbot", NOW)
    assert parsed.command == command
    assert parsed.chat_id == CONFIG.sender_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("from", {"id": 999, "is_bot": False}),
        ("from", {"id": "123456", "is_bot": False}),
        ("from", {"id": True, "is_bot": False}),
        ("from", {"id": 123456, "is_bot": True}),
        ("chat", {"id": -123456, "type": "group"}),
        ("chat", {"id": 123456, "type": "supergroup"}),
        ("chat", {"id": 999, "type": "private"}),
        ("date", int(NOW.timestamp()) - 86401),
        ("date", int(NOW.timestamp()) + 61),
        ("date", True),
    ],
)
def test_refuses_wrong_identity_chat_or_date(field, value):
    row = update()
    row["message"][field] = value
    assert parse_update(row, CONFIG, "MyJarvisBot", NOW) is None


@pytest.mark.parametrize(
    "field",
    [
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
    ],
)
def test_refuses_forwarded_or_delegated_messages_even_if_field_empty(field):
    row = update()
    row["message"][field] = None
    assert parse_update(row, CONFIG, "MyJarvisBot", NOW) is None


def test_non_message_updates_and_other_bot_mentions_are_ignored():
    row = update()
    edited = {"update_id": 100, "edited_message": deepcopy(row["message"])}
    assert parse_update(edited, CONFIG, "MyJarvisBot", NOW) is None
    assert parse_update(update("/status@OtherBot"), CONFIG, "MyJarvisBot", NOW) is None
    assert parse_update(update("/jarvis_setup nonce"), CONFIG, "MyJarvisBot", NOW) is None


def test_chat_content_is_transient_and_pair_secret_not_in_repr():
    secret_text = "PRIVATE-DOCUMENT-CONTENT"
    parsed = parse_update(update(secret_text), CONFIG, "MyJarvisBot", NOW)
    assert parsed.command == "chat"
    assert parsed.argument == secret_text
    assert secret_text not in repr(parsed)
    row = update()
    row["message"].pop("text")
    row["message"]["document"] = {"file_id": "PRIVATE-FILE-ID"}
    assert parse_update(row, CONFIG, "MyJarvisBot", NOW).command == "unsupported"
    paired = parse_update(update("/pair secret-pair-code"), CONFIG, "MyJarvisBot", NOW)
    assert paired.pair_code == "secret-pair-code"
    assert "secret-pair-code" not in repr(paired)
    oversized = parse_update(update("/pair " + "x" * 201), CONFIG, "MyJarvisBot", NOW)
    assert oversized.pair_code is None
    assert all(0 < len(text) <= 4096 for text in REPLIES.values())


@pytest.mark.parametrize("identifier", [-1, True, "100", 2**63 - 1])
def test_invalid_update_identifier_rejected(identifier):
    with pytest.raises(ValueError):
        parse_update(update(update_id=identifier), CONFIG, "MyJarvisBot", NOW)
