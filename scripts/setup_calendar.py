"""Local Google Calendar enrollment. Python standard library only.

Run on the desktop with the browser, not in the scheduler container.
No Calendar API call, database write, grant, or scheduler activation occurs here.
"""

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import secrets
import stat
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

SCOPE = "https://www.googleapis.com/auth/calendar.events.owned.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_HOST = "oauth2.googleapis.com"
SECRET_FILES = ("google_client_id", "google_client_secret", "google_refresh_token")
MAX_RESPONSE = 16384


class SetupError(RuntimeError):
    """Only locally defined, credential-free error messages may be exposed."""


def linked(path):
    if path.is_symlink():
        return True
    try:
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except FileNotFoundError:
        return False


def secret_value(value, *, limit=8192):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limit
        or not value.isascii()
        or any(not 33 <= ord(c) <= 126 for c in value)
    ):
        raise SetupError("calendar_invalid_credential_format")
    return value


def private_folder(root, *, write_candidate=False):
    folder = root / ".secrets"
    if linked(folder) or not folder.is_dir():
        raise SetupError(
            "Existing private .secrets directory required; do not run setup_local again"
        )
    if os.name != "nt" and stat.S_IMODE(folder.stat().st_mode) & 0o077:
        raise SetupError("calendar_secrets_directory_must_be_private_0700")
    if write_candidate:
        folder = folder / "calendar_write"
        if linked(folder):
            raise SetupError("calendar_candidate_directory_must_not_be_linked")
        folder.mkdir(mode=0o700, exist_ok=True)
        if not folder.is_dir():
            raise SetupError("calendar_candidate_directory_required")
        if os.name != "nt" and stat.S_IMODE(folder.stat().st_mode) & 0o077:
            raise SetupError("calendar_candidate_directory_must_be_private_0700")
    for name in SECRET_FILES:
        if (folder / name).exists() or linked(folder / name):
            raise SetupError("Calendar credentials already exist; refusing to rotate or overwrite")
    return folder


def load_client(path):
    if linked(path) or not path.is_file() or path.stat().st_size > MAX_RESPONSE:
        raise SetupError("Use the downloaded Desktop app JSON, at most 16 KiB")
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError
        document = json.loads(raw)
        if not isinstance(document, dict) or "web" in document:
            raise ValueError
        client = document["installed"]
        client_id = secret_value(client["client_id"], limit=512)
        client_secret = secret_value(client["client_secret"], limit=4096)
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", client_id):
            raise ValueError
        # Never take HTTP destinations from a credential file.
        return client_id, client_secret
    except (ValueError, KeyError, TypeError, UnicodeError, SetupError):
        raise SetupError("Invalid Desktop app JSON; no credential values printed") from None


def require_scope(scope):
    if scope not in (SCOPE, WRITE_SCOPE):
        raise SetupError("calendar_scope_not_supported")


def make_authorization(client_id, redirect_uri, state, verifier, *, scope=SCOPE):
    require_scope(scope)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scope,
                "access_type": "offline",
                "prompt": "consent select_account",
                "include_granted_scopes": "false",
                "state": state,
                "code_challenge": challenge.rstrip(b"=").decode("ascii"),
                "code_challenge_method": "S256",
            }
        )
    )


def callback(path, host, expected_host, state):
    """Validate the callback before accepting either a code or a denial."""
    if host != expected_host or len(path) > 8192:
        raise SetupError("calendar_callback_rejected")
    try:
        target = urlsplit(path)
        if target.scheme or target.netloc or target.fragment or target.path != "/oauth2callback":
            raise ValueError
        values = parse_qs(target.query, keep_blank_values=True, max_num_fields=12)
        if any(len(v) != 1 for v in values.values()):
            raise ValueError
        returned_state = values.get("state", [""])[0]
        if not secrets.compare_digest(returned_state.encode("utf-8"), state.encode("ascii")):
            raise ValueError
        if "error" in values:
            if "code" in values:
                raise ValueError
            return None, "calendar_consent_denied"
        return secret_value(values["code"][0], limit=4096), None
    except (ValueError, KeyError, UnicodeError, SetupError):
        raise SetupError("calendar_callback_rejected") from None


def authorize(client_id, *, scope=SCOPE, timeout=300, browser=None):
    require_scope(scope)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(3)
            super().setup()

        def log_message(self, *_args):
            pass  # The callback URL contains a one-use authorization code.

        def do_GET(self):
            try:
                code, error = callback(self.path, self.headers.get("Host"), expected_host, state)
                if result:
                    raise SetupError("calendar_callback_rejected")
            except SetupError:
                status = 400
                message = b"Invalid callback. Return to the Google authorization window."
            else:
                result.update(code=code, error=error)
                status = 200
                message = b"Authorization response received. Return to PowerShell for the result."
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(message)
            except OSError:
                pass

        def do_POST(self):
            self.send_error(405, "Method not allowed")

    class QuietServer(HTTPServer):
        def handle_error(self, *_args):
            pass  # Do not print exception traces containing request details.

    with QuietServer(("127.0.0.1", 0), Handler) as server:
        expected_host = f"127.0.0.1:{server.server_port}"
        redirect_uri = f"http://{expected_host}/oauth2callback"
        url = make_authorization(client_id, redirect_uri, state, verifier, scope=scope)
        access = "baca saja" if scope == SCOPE else "baca, buat, ubah dan hapus acara milik akun"
        print(f"Membuka login Google. Pilih akun pemilik kalender; akses {access}.")
        if not (browser or webbrowser.open)(url):
            raise SetupError("calendar_browser_unavailable; configure a desktop default browser")
        deadline = time.monotonic() + timeout
        attempts = 0
        while not result and time.monotonic() < deadline and attempts < 600:
            server.timeout = min(1.0, max(0.01, deadline - time.monotonic()))
            server.handle_request()
            attempts += 1
    if not result:
        raise SetupError("calendar_login_timeout; no credentials saved")
    if result["error"]:
        raise SetupError(result["error"])
    return result["code"], verifier, redirect_uri


def exchange(client_id, client_secret, code, verifier, redirect_uri, *, scope=SCOPE):
    """Fixed HTTPS endpoint, normal TLS verification, no redirects or env proxy."""
    require_scope(scope)
    connection = http.client.HTTPSConnection(TOKEN_HOST, timeout=20)
    try:
        connection.request(
            "POST",
            "/token",
            body=urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                }
            ).encode("ascii"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise SetupError("calendar_token_exchange_denied; check OAuth client and consent")
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise SetupError("calendar_token_response_too_large")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        if data.get("token_type", "").lower() != "bearer":
            raise ValueError
        secret_value(data["access_token"])
        refresh = secret_value(data["refresh_token"])
        if type(data.get("expires_in")) is not int or not 60 <= data["expires_in"] <= 86400:
            raise ValueError
        granted = set(data["scope"].split()) if isinstance(data.get("scope"), str) else set()
        allowed = {scope} if scope == SCOPE else {WRITE_SCOPE, SCOPE}
        if scope not in granted or not granted.issubset(allowed):
            raise SetupError("calendar_scope_mismatch; consent must match the requested access")
        return refresh
    except (OSError, http.client.HTTPException):
        raise SetupError("calendar_token_transport_error; no credentials saved") from None
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise SetupError("calendar_token_response_invalid; no credentials saved") from None
    finally:
        connection.close()


def save(folder, client_id, client_secret, refresh_token):
    values = dict(zip(SECRET_FILES, (client_id, client_secret, refresh_token), strict=True))
    for value in values.values():
        secret_value(value)
    created = []
    try:
        for name, value in values.items():
            path = folder / name
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as output:
                created.append(path)
                output.write(value.encode("ascii") + b"\n")
                output.flush()
                os.fsync(output.fileno())
            path.chmod(0o444)
    except BaseException:
        for path in created:
            path.chmod(0o600)
            path.unlink()
        raise


def setup(root, client_path, *, access="read"):
    if access not in ("read", "write"):
        raise SetupError("calendar_access_not_supported")
    candidate = access == "write"
    scope = WRITE_SCOPE if candidate else SCOPE
    folder = private_folder(root, write_candidate=candidate)
    client_id, client_secret = load_client(client_path)
    lock = folder / ".calendar-setup.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise SetupError("calendar_setup_locked; another setup may still be running") from None
    try:
        private_folder(root, write_candidate=candidate)  # Recheck inside the setup lock.
        code, verifier, redirect_uri = authorize(client_id, scope=scope)
        refresh = exchange(client_id, client_secret, code, verifier, redirect_uri, scope=scope)
        save(folder, client_id, client_secret, refresh)
    finally:
        lock.rmdir()
    return {
        "calendar_credentials_saved": True,
        "scope": scope,
        "candidate_only": candidate,
        "directory": ".secrets/calendar_write" if candidate else ".secrets",
        "files": list(SECRET_FILES),
        "scheduler_started": False,
        "grant_changed": False,
        "calendar_api_called": False,
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Enroll Calendar access on this desktop")
    parser.add_argument("--access", choices=("read", "write"), default="read")
    parser.add_argument(
        "--client-json", type=Path, default=root / ".secrets" / "google_oauth_client.json"
    )
    args = parser.parse_args()
    try:
        folder = ".secrets/calendar_write" if args.access == "write" else ".secrets"
        print(f"File token akan disimpan di {folder}. Jaga folder ini privat pada Windows/NTFS.")
        if args.access == "write":
            print(
                "Kandidat terpisah; aktivasi scheduler dan grant dilakukan setelah login berhasil."
            )
        print(json.dumps(setup(root, args.client_json, access=args.access)))
    except SetupError as exc:
        print(f"Setup dihentikan: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Setup dibatalkan.", file=sys.stderr)
        return 130
    except Exception:
        print(
            "Setup gagal. Periksa file, izin folder, dan jaringan; jangan kirim kredensial.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
