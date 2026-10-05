from uuid import uuid4

import pytest
from pydantic import SecretStr

from jarvis.core.errors import ApplicationError
from jarvis.identity.crypto import issue_material, matches, parse_token
from jarvis.identity.service import Principal
from jarvis.policies.privacy import (
    DataClass,
    EndpointPolicy,
    RouteDecision,
    cloud_request_constraints,
    route_decision,
)


def test_token_randomness_and_owner_binding(settings):
    owner = uuid4()
    record, secret, hashed = issue_material(owner, settings.token_pepper)
    raw = secret.get_secret_value()
    assert parse_token(raw).owner_id == owner
    assert parse_token(raw).record_id == record
    assert len(hashed) == 32
    assert matches(raw, hashed, settings.token_pepper)
    assert not matches(raw.replace(str(owner), str(uuid4())), hashed, settings.token_pepper)
    assert not matches(raw, hashed, SecretStr("other-pepper"))
    assert issue_material(owner, settings.token_pepper)[1] != secret
    assert raw not in repr(secret)


@pytest.mark.parametrize("raw", ["", "Bearer x", "jvt1.a.b.c", "ü", "a" * 161])
def test_invalid_token_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_token(raw)


def test_pairing_credentials_cannot_authenticate_as_api_token(settings):
    _, secret, _ = issue_material(uuid4(), settings.token_pepper, "jvp1")
    with pytest.raises(ValueError):
        parse_token(secret.get_secret_value())
    assert parse_token(secret.get_secret_value(), "jvp1")


@pytest.mark.parametrize(
    "training,zdr,paid,expected",
    [
        (None, None, False, RouteDecision.DENIED),
        (None, True, False, RouteDecision.DENIED),
        (True, True, False, RouteDecision.DENIED),
        (False, None, False, RouteDecision.DENIED),
        (False, False, False, RouteDecision.DENIED),
        (False, True, False, RouteDecision.ELIGIBLE_FREE),
        (False, True, True, RouteDecision.APPROVAL_REQUIRED),
        (False, True, None, RouteDecision.DENIED),
    ],
)
def test_cloud_policy_requires_explicit_privacy_and_paid_consent(training, zdr, paid, expected):
    endpoint = EndpointPolicy(training, zdr, paid)
    assert route_decision(DataClass.PERSONAL, endpoint) == expected
    assert route_decision(DataClass.PUBLIC, endpoint) == expected
    assert route_decision(DataClass.RESTRICTED, endpoint) == RouteDecision.DENIED


def test_cloud_constraints_disable_collection_and_plugins():
    value = cloud_request_constraints()
    assert value["provider"]["data_collection"] == "deny"
    assert value["provider"]["zdr"] is True
    assert value["plugins"] == []


def test_scope_denial():
    principal = Principal(uuid4(), uuid4(), frozenset({"profile:read"}))
    principal.require("profile:read")
    with pytest.raises(ApplicationError) as error:
        principal.require("ops:metrics")
    assert error.value.status == 403
