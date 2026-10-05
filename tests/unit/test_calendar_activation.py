from uuid import uuid4

from pydantic import SecretStr

from jarvis.integrations.calendar.activation import activate_google_calendar


def test_activation_builds_closed_calendar_runtime_without_exposing_secrets():
    activation = activate_google_calendar(
        object(),
        uuid4(),
        client_id=SecretStr("client"),
        client_secret=SecretStr("secret"),
        refresh_token=SecretStr("refresh"),
    )
    assert set(activation.registry.names()) == {
        "calendar_list_events",
        "calendar_create_event",
        "calendar_create_invite",
        "calendar_update_event",
        "calendar_delete_event",
    }
    assert activation.agents.names() == ("calendar",)


def test_activation_registry_has_no_oauth_tool():
    activation = activate_google_calendar(
        object(),
        uuid4(),
        client_id=SecretStr("client"),
        client_secret=SecretStr("secret"),
        refresh_token=SecretStr("refresh"),
    )
    assert not any("oauth" in name or "token" in name for name in activation.registry.names())
