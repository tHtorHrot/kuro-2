import base64
import hashlib
import http.client
import importlib.util
import json
import os
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("setup_calendar", ROOT / "scripts/setup_calendar.py")
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)
CLIENT_ID = "123-example.apps.googleusercontent.com"


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / ".secrets"
    folder.mkdir(mode=0o700)
    client = folder / "google_oauth_client.json"
    client.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": CLIENT_ID,
                    "client_secret": "synthetic-client-secret",
                    "token_uri": "https://untrusted.example/token",
                }
            }
        )
    )
    return tmp_path, folder, client


def test_pkce_and_read_only_authorization():
    verifier = "v" * 64
    url = wizard.make_authorization(
        CLIENT_ID, "http://127.0.0.1:5555/oauth2callback", "nonce", verifier
    )
    params = parse_qs(urlsplit(url).query)
    assert url.startswith(wizard.AUTH_URL + "?")
    assert params["scope"] == [wizard.SCOPE]
    assert params["access_type"] == ["offline"]
    assert params["include_granted_scopes"] == ["false"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    ]
    assert "client_secret" not in params and "code_verifier" not in params


@pytest.mark.parametrize(
    "query",
    [
        "code=secret-code",
        "state=wrong&code=secret-code",
        "state=nonce&state=nonce&code=x",
        "state=nonce&code=x&code=y",
        "state=nonce&code=x&error=denied",
        "state=nonce&code=",
        "state=nonce&code=a%0Ab",
        "state=nonce&code=%C3%A9",
        "state=nonce&code=" + "x" * 8192,
        "state=nonce&" + "&".join("p" + str(i) + "=v" for i in range(20)),
    ],
)
def test_invalid_callback_never_returns_code(query):
    with pytest.raises(wizard.SetupError, match="calendar_callback_rejected") as error:
        wizard.callback("/oauth2callback?" + query, "127.0.0.1:1", "127.0.0.1:1", "nonce")
    assert "secret-code" not in str(error.value)


@pytest.mark.parametrize(
    "path,host",
    [
        ("/wrong?state=nonce&code=x", "127.0.0.1:1"),
        ("/oauth2callback?state=nonce&code=x", "evil.example:1"),
        ("http://evil.example/oauth2callback?state=nonce&code=x", "127.0.0.1:1"),
        ("/oauth2callback?state=nonce&code=x#frag", "127.0.0.1:1"),
    ],
)
def test_callback_origin_and_path_are_bound(path, host):
    with pytest.raises(wizard.SetupError):
        wizard.callback(path, host, "127.0.0.1:1", "nonce")


def test_denial_is_validated_and_sanitized():
    assert wizard.callback(
        "/oauth2callback?state=nonce&error=private-error-data",
        "127.0.0.1:1",
        "127.0.0.1:1",
        "nonce",
    ) == (None, "calendar_consent_denied")
    assert wizard.callback(
        "/oauth2callback?state=nonce&code=synthetic-code", "127.0.0.1:1", "127.0.0.1:1", "nonce"
    ) == ("synthetic-code", None)


def test_loopback_accepts_only_correct_flow_without_logging_codes(capsys):
    requests = []
    threads = []

    def browser(url):
        params = parse_qs(urlsplit(url).query)
        redirect = urlsplit(params["redirect_uri"][0])
        assert redirect.hostname == "127.0.0.1"

        def send():
            for state in ("wrong", params["state"][0]):
                connection = http.client.HTTPConnection(redirect.hostname, redirect.port, timeout=3)
                connection.request(
                    "GET",
                    redirect.path + "?" + urlencode({"state": state, "code": "private-auth-code"}),
                )
                response = connection.getresponse()
                requests.append(response.status)
                assert response.getheader("Cache-Control") == "no-store"
                assert b"private-auth-code" not in response.read()
                connection.close()

        thread = threading.Thread(target=send)
        threads.append(thread)
        thread.start()
        return True

    code, verifier, redirect = wizard.authorize(CLIENT_ID, timeout=5, browser=browser)
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()
    assert requests == [400, 200]
    assert code == "private-auth-code" and 43 <= len(verifier) <= 128
    assert redirect.startswith("http://127.0.0.1:")
    captured = capsys.readouterr()
    assert code not in captured.out + captured.err


def test_browser_and_timeout_fail_closed():
    with pytest.raises(wizard.SetupError, match="browser_unavailable"):
        wizard.authorize(CLIENT_ID, browser=lambda _: False)
    with pytest.raises(wizard.SetupError, match="login_timeout"):
        wizard.authorize(CLIENT_ID, timeout=0.01, browser=lambda _: True)


def token_reply(**changes):
    return {
        "access_token": "private-access",
        "refresh_token": "private-refresh",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": wizard.SCOPE,
        **changes,
    }


def mock_token(monkeypatch, body, *, status=200):
    calls = []

    class Response:
        def __init__(self):
            self.status = status

        def read(self, limit):
            return body[:limit]

    class Connection:
        def __init__(self, host, timeout):
            assert host == "oauth2.googleapis.com" and timeout == 20

        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))

        def getresponse(self):
            return Response()

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(wizard.http.client, "HTTPSConnection", Connection)
    return calls


def test_exchange_checks_scope_and_keeps_fixed_origin(monkeypatch, project):
    _, _, client = project
    client_id, client_secret = wizard.load_client(client)
    calls = mock_token(monkeypatch, json.dumps(token_reply()).encode())
    assert (
        wizard.exchange(
            client_id, client_secret, "auth-code", "verifier", "http://127.0.0.1:1/oauth2callback"
        )
        == "private-refresh"
    )
    assert calls[0][0:2] == ("POST", "/token")
    body = parse_qs(calls[0][2]["body"].decode())
    assert body["code_verifier"] == ["verifier"] and body["grant_type"] == ["authorization_code"]
    assert calls[-1] == "closed"


@pytest.mark.parametrize(
    "changes",
    [
        {"refresh_token": None},
        {"access_token": "a\nb"},
        {"token_type": "MAC"},
        {"expires_in": True},
        {"expires_in": 1},
        {"scope": None},
        {"scope": "https://www.googleapis.com/auth/calendar.events"},
        {"scope": wizard.SCOPE + " https://www.googleapis.com/auth/calendar"},
    ],
)
def test_unusable_or_excessive_token_rejected(monkeypatch, changes):
    mock_token(monkeypatch, json.dumps(token_reply(**changes)).encode())
    with pytest.raises(wizard.SetupError) as error:
        wizard.exchange(CLIENT_ID, "secret", "code", "verifier", "redirect")
    assert "private-refresh" not in str(error.value)


@pytest.mark.parametrize(
    "body,status",
    [(b"private-body", 400), (b"private-body", 302), (b"x" * 20000, 200), (b"[]", 200)],
)
def test_provider_errors_are_bounded_and_private(monkeypatch, body, status):
    calls = mock_token(monkeypatch, body, status=status)
    with pytest.raises(wizard.SetupError) as error:
        wizard.exchange(CLIENT_ID, "secret", "code", "verifier", "redirect")
    assert "private-body" not in str(error.value)
    assert calls[-1] == "closed"


def test_existing_and_web_clients_rejected_before_browser(project, monkeypatch):
    root, folder, client = project
    (folder / "google_client_id").write_text("keep-existing")
    monkeypatch.setattr(wizard, "authorize", lambda *_, **__: pytest.fail("Browser must not open"))
    with pytest.raises(wizard.SetupError, match="already exist"):
        wizard.setup(root, client)
    assert (folder / "google_client_id").read_text() == "keep-existing"
    client.write_text(json.dumps({"web": {"client_secret": "private-client"}}))
    with pytest.raises(wizard.SetupError, match="Desktop") as error:
        wizard.load_client(client)
    assert "private-client" not in str(error.value)


def test_complete_setup_preserves_existing_files_and_saves_lf(project, monkeypatch, capsys):
    root, folder, client = project
    (folder / "token_pepper").write_text("keep-this")
    monkeypatch.setattr(wizard, "authorize", lambda *_, **__: ("code", "verifier", "redirect"))
    monkeypatch.setattr(wizard, "exchange", lambda *_, **__: "synthetic-refresh")
    result = wizard.setup(root, client)
    assert result["calendar_credentials_saved"] and not result["scheduler_started"]
    assert not result["grant_changed"] and not result["calendar_api_called"]
    assert (folder / "token_pepper").read_text() == "keep-this"
    assert (folder / "google_refresh_token").read_bytes() == b"synthetic-refresh\n"
    for name in wizard.SECRET_FILES:
        data = (folder / name).read_bytes()
        assert data.endswith(b"\n") and b"\r" not in data
    assert not (folder / ".calendar-setup.lock").exists()
    assert "synthetic-refresh" not in capsys.readouterr().out


def test_write_failure_removes_only_new_files(project, monkeypatch):
    _, folder, _ = project
    real_open = os.open

    def fail_second(path, flags, mode):
        if Path(path).name == "google_client_secret":
            raise OSError("simulated")
        return real_open(path, flags, mode)

    monkeypatch.setattr(wizard.os, "open", fail_second)
    with pytest.raises(OSError):
        wizard.save(folder, CLIENT_ID, "secret", "refresh")
    assert not any((folder / name).exists() for name in wizard.SECRET_FILES)
    assert (folder / "google_oauth_client.json").is_file()


def test_concurrent_setup_and_denial_leave_no_credentials(project, monkeypatch):
    root, folder, client = project
    lock = folder / ".calendar-setup.lock"
    lock.mkdir()
    with pytest.raises(wizard.SetupError, match="setup_locked"):
        wizard.setup(root, client)
    lock.rmdir()

    def denied(*_, **__):
        raise wizard.SetupError("calendar_consent_denied")

    monkeypatch.setattr(wizard, "authorize", denied)
    with pytest.raises(wizard.SetupError, match="consent_denied"):
        wizard.setup(root, client)
    assert not lock.exists()
    assert not any((folder / name).exists() for name in wizard.SECRET_FILES)


def test_write_enrollment_keeps_live_read_credentials_and_targets_a_separate_directory(
    project, monkeypatch
):
    root, folder, client = project
    originals = {name: f"existing-{name}\n" for name in wizard.SECRET_FILES}
    for name, value in originals.items():
        (folder / name).write_text(value)

    def authorize(client_id, *, scope):
        assert client_id == CLIENT_ID and scope == wizard.WRITE_SCOPE
        return "code", "verifier", "redirect"

    def exchange(*_, scope):
        assert scope == wizard.WRITE_SCOPE
        return "synthetic-write-refresh"

    monkeypatch.setattr(wizard, "authorize", authorize)
    monkeypatch.setattr(wizard, "exchange", exchange)
    result = wizard.setup(root, client, access="write")
    assert result["candidate_only"] and result["directory"] == ".secrets/calendar_write"
    assert result["scope"] == wizard.WRITE_SCOPE
    assert not any(result[k] for k in ("grant_changed", "scheduler_started", "calendar_api_called"))
    assert (
        folder / "calendar_write/google_refresh_token"
    ).read_bytes() == b"synthetic-write-refresh\n"
    assert not (folder / "calendar_write/.calendar-setup.lock").exists()
    for name, value in originals.items():
        assert (folder / name).read_text() == value


@pytest.mark.parametrize("returned", [wizard.WRITE_SCOPE, wizard.WRITE_SCOPE + " " + wizard.SCOPE])
def test_write_token_accepts_only_owned_event_access(monkeypatch, returned):
    mock_token(monkeypatch, json.dumps(token_reply(scope=returned)).encode())
    assert wizard.exchange(CLIENT_ID, "secret", "code", "v", "r", scope=wizard.WRITE_SCOPE)
    params = parse_qs(
        urlsplit(
            wizard.make_authorization(
                CLIENT_ID, "redirect", "nonce", "verifier", scope=wizard.WRITE_SCOPE
            )
        ).query
    )
    assert params["scope"] == [wizard.WRITE_SCOPE]
    assert params["include_granted_scopes"] == ["false"]


@pytest.mark.parametrize(
    "returned", [wizard.SCOPE, wizard.WRITE_SCOPE + " https://www.googleapis.com/auth/calendar"]
)
def test_write_token_rejects_missing_or_excessive_permission(monkeypatch, returned):
    mock_token(monkeypatch, json.dumps(token_reply(scope=returned)).encode())
    with pytest.raises(wizard.SetupError, match="scope_mismatch"):
        wizard.exchange(CLIENT_ID, "secret", "code", "v", "r", scope=wizard.WRITE_SCOPE)


def test_existing_candidate_or_linked_candidate_fails_before_browser(project, monkeypatch):
    root, folder, client = project
    monkeypatch.setattr(wizard, "authorize", lambda *_, **__: pytest.fail("Browser must not open"))
    candidate = folder / "calendar_write"
    candidate.mkdir(mode=0o700)
    token = candidate / "google_refresh_token"
    token.write_text("keep-candidate")
    with pytest.raises(wizard.SetupError, match="already exist"):
        wizard.setup(root, client, access="write")
    assert token.read_text() == "keep-candidate"
    token.unlink()
    candidate.rmdir()
    candidate.symlink_to(folder, target_is_directory=True)
    with pytest.raises(wizard.SetupError, match="must_not_be_linked"):
        wizard.setup(root, client, access="write")


def test_write_denial_preserves_live_tokens_and_releases_candidate_lock(project, monkeypatch):
    root, folder, client = project
    (folder / "google_refresh_token").write_text("keep-live")

    def denied(*_, **__):
        raise wizard.SetupError("calendar_consent_denied")

    monkeypatch.setattr(wizard, "authorize", denied)
    with pytest.raises(wizard.SetupError, match="consent_denied"):
        wizard.setup(root, client, access="write")
    assert (folder / "google_refresh_token").read_text() == "keep-live"
    candidate = folder / "calendar_write"
    assert not (candidate / ".calendar-setup.lock").exists()
    assert not any((candidate / name).exists() for name in wizard.SECRET_FILES)


def test_arbitrary_access_or_scope_is_rejected_before_external_work(project, monkeypatch):
    root, _, client = project
    monkeypatch.setattr(wizard, "authorize", lambda *_, **__: pytest.fail("Browser must not open"))
    with pytest.raises(wizard.SetupError, match="access_not_supported"):
        wizard.setup(root, client, access="all")
    with pytest.raises(wizard.SetupError, match="scope_not_supported"):
        wizard.make_authorization(CLIENT_ID, "redirect", "nonce", "v", scope="all")
