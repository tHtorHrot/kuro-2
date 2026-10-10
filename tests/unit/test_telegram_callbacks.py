from datetime import UTC, datetime
from uuid import uuid4

from jarvis.interfaces.telegram.callbacks import (
    APPROVE_PREFIX,
    CANCEL_PREFIX,
    proposal_markup,
)
from jarvis.interfaces.telegram.commands import parse_callback
from jarvis.interfaces.telegram.config import TelegramConfig


def config():
    return TelegramConfig(owner_id=uuid4(), sender_id=111, bot_id=222)


def query(data="approve:12345678-1234-5678-1234-567812345678", sender=111, chat=111):
    now = int(datetime.now(UTC).timestamp())
    return {
        "id": "cb1",
        "from": {"id": sender, "is_bot": False},
        "message": {
            "message_id": 7,
            "date": now,
            "text": "proposal",
            "chat": {"id": chat, "type": "private"},
        },
        "data": data,
    }


def test_parse_callback_accepts_own_private_tap():
    parsed = parse_callback(50, query(), config(), datetime.now(UTC))
    assert parsed.command == "callback" and parsed.update_id == 50
    assert parsed.callback_id == "cb1" and parsed.callback_message_id == 7
    assert parsed.argument.startswith(APPROVE_PREFIX)


def test_parse_callback_rejects_foreign_group_and_oversize_data():
    cfg, now = config(), datetime.now(UTC)
    assert parse_callback(51, query(sender=999), cfg, now) is None
    assert parse_callback(52, query(chat=333), cfg, now) is None
    bad = query()
    bad["message"]["chat"] = {"id": 111, "type": "group"}
    assert parse_callback(53, bad, cfg, now) is None
    assert parse_callback(54, query(data="x" * 65), cfg, now) is None
    assert parse_callback(55, {"id": "cb", "from": {"id": 111}}, cfg, now) is None


def test_proposal_markup_only_for_server_toolapprove_lines():
    action_id, fingerprint = str(uuid4()), "f" * 64
    markup = proposal_markup(f"/toolapprove {action_id} {fingerprint}")
    buttons = markup["inline_keyboard"][0]
    assert buttons[0] == {"text": "Setuju ✓", "callback_data": APPROVE_PREFIX + action_id}
    assert buttons[1] == {"text": "Batal", "callback_data": CANCEL_PREFIX + action_id}
    assert all(len(b["callback_data"]) <= 64 for b in buttons)
    assert proposal_markup("Halo biasa") is None
    assert proposal_markup(None) is None
    assert proposal_markup(f"/toolapprove short {fingerprint}") is None
