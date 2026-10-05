from copy import deepcopy
from uuid import uuid4

import pytest

from jarvis.integrations.calendar.recovery import verify_solo_result


def values():
    action_id = uuid4()
    args = {
        "title": "Review",
        "start": "2026-10-05T10:00:00+07:00",
        "end": "2026-10-05T11:00:00+07:00",
        "timezone": "Asia/Jakarta",
    }
    result = {
        "id": "kuro" + action_id.hex,
        "summary": "Review",
        "start": {"dateTime": "2026-10-05T03:00:00Z"},
        "end": {"dateTime": "2026-10-05T04:00:00Z"},
    }
    return action_id, args, result


def test_reconciliation_accepts_same_instants_and_stable_provider_identity():
    action_id, args, result = values()
    assert verify_solo_result(action_id, args, result)


@pytest.mark.parametrize(
    "change",
    [
        {"id": "unrelated"},
        {"status": "cancelled"},
        {"summary": "Altered title"},
        {"start": {}},
        {"end": None},
        {"start": {"dateTime": "2026-10-05T10:00:00Z"}},
        {"end": {"dateTime": "2026-10-05T11:00:00"}},
    ],
)
def test_reconciliation_rejects_wrong_event_or_unverified_payload(change):
    action_id, args, result = values()
    assert not verify_solo_result(action_id, args, {**deepcopy(result), **change})
