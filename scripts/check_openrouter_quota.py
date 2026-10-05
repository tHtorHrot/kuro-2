"""Read free-model quota with one metadata GET; no inference or file changes.

Run from the existing project directory:
    python scripts/check_openrouter_quota.py

Uses only the Python standard library. The existing credential is read locally;
only a fixed HTTPS OpenRouter endpoint receives it. No exception payload, API key,
account label, request/response text or account balance is printed.

Reference: https://openrouter.ai/docs/api_reference/limits
"""

import http.client
import json
import socket
import ssl
import time
from pathlib import Path


def check_quota(project):
    result = {
        "inference_sent": False,
        "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        with (project / ".secrets" / "openrouter_key").open("rb") as source:
            raw_key = source.read(520)
        key = raw_key.decode("ascii").strip("\r\n")
        if not 20 <= len(key) <= 512 or any(c.isspace() for c in key):
            raise ValueError()
    except (OSError, UnicodeError, ValueError):
        return {**result, "status": "local_key_missing_or_invalid"}

    connection = None
    try:
        # HTTPSConnection verifies TLS, ignores proxy environment variables and
        # does not follow redirects. No database or Telegram access is involved.
        connection = http.client.HTTPSConnection("openrouter.ai", timeout=20)
        connection.request(
            "GET",
            "/api/v1/key",
            headers={"Authorization": "Bearer " + key, "Accept-Encoding": "identity"},
        )
        response = connection.getresponse()
        result["http_status"] = response.status
        if response.status != 200:
            return {**result, "status": "metadata_request_rejected"}
        raw = response.read(65537)
        if len(raw) > 65536:
            return {**result, "status": "metadata_response_too_large"}
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return {**result, "status": "metadata_format_unrecognized"}
        quota = payload["data"].get("free_model_daily_requests")
        fields = ("used", "limit", "remaining")
        if not isinstance(quota, dict) or not all(
            type(quota.get(field)) is int and 0 <= quota[field] <= 1_000_000_000 for field in fields
        ):
            return {**result, "status": "quota_not_reported"}
        return {
            **result,
            "status": "quota_available",
            "free_requests_today": {field: quota[field] for field in fields},
        }
    except ssl.SSLError:
        return {**result, "status": "tls_check_failed"}
    except socket.gaierror:
        return {**result, "status": "dns_lookup_failed"}
    except TimeoutError:
        return {**result, "status": "metadata_timeout"}
    except (OSError, http.client.HTTPException):
        return {**result, "status": "metadata_connection_failed"}
    except (ValueError, TypeError, UnicodeError):
        return {**result, "status": "metadata_format_unrecognized"}
    finally:
        if connection is not None:
            connection.close()


def main():
    try:
        result = check_quota(Path.cwd())
    except KeyboardInterrupt:
        result = {"inference_sent": False, "status": "cancelled"}
    except Exception:
        # Never print a traceback or a transport exception carrying credentials.
        result = {"inference_sent": False, "status": "check_failed"}
    print(json.dumps(result))
    return 0 if result["status"] in {"quota_available", "quota_not_reported"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
