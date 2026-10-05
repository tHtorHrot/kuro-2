from uuid import uuid4

import pytest

from jarvis.tools import ToolProposal, action_fingerprint
from jarvis.tools.journal import ActionJournalError


def test_action_fingerprint_is_canonical_and_owner_bound():
    owner = uuid4()
    a = ToolProposal("calendar_move", {"start": "10:00", "event_id": "e1"})
    b = ToolProposal("calendar_move", {"event_id": "e1", "start": "10:00"})
    assert action_fingerprint(owner, a) == action_fingerprint(owner, b)
    assert action_fingerprint(owner, a) != action_fingerprint(uuid4(), a)
    changed = ToolProposal("calendar_move", {"event_id": "e1", "start": "11:00"})
    assert action_fingerprint(owner, a) != action_fingerprint(owner, changed)


def test_action_fingerprint_rejects_non_json_or_non_finite_arguments():
    owner = uuid4()
    with pytest.raises(ActionJournalError, match="arguments_not_json"):
        action_fingerprint(owner, ToolProposal("x", {"value": object()}))
    with pytest.raises(ActionJournalError, match="arguments_not_json"):
        action_fingerprint(owner, ToolProposal("x", {"value": float("nan")}))
