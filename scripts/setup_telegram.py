"""Interactive Windows/Linux setup using stdlib only; never echo a Telegram token."""

import argparse
import getpass
import http.client
import json
import os
import re
import secrets
import sys
import time
import warnings
from pathlib import Path
from uuid import UUID


class SetupError(RuntimeError):
    pass


def call(token: str, method: str, payload: dict) -> object:
    if method not in {"getMe", "getWebhookInfo", "getUpdates"}:
        raise SetupError("Setup method is not allowed")
    connection = http.client.HTTPSConnection("api.telegram.org", timeout=35)
    try:
        connection.request(
            "POST",
            "/bot" + token + "/" + method,
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
        )
        response = connection.getresponse()
        body = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(body) > 1024 * 1024:
            raise SetupError("Telegram setup request rejected; check connectivity/token/webhook")
        data = json.loads(body)
        if not isinstance(data, dict) or data.get("ok") is not True or "result" not in data:
            raise SetupError("Telegram returned an invalid setup response")
        return data["result"]
    except (OSError, http.client.HTTPException, ValueError):
        raise SetupError(
            "Telegram setup failed; no response or credential details were printed"
        ) from None
    finally:
        connection.close()


def detect_sender(updates: object, challenge: str, started: float) -> int | None:
    if not isinstance(updates, list) or len(updates) > 100:
        raise SetupError("Unexpected setup updates")
    found = set()
    for update in updates:
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict) or message.get("text") != challenge:
            continue
        sender, chat = message.get("from"), message.get("chat")
        if not isinstance(sender, dict) or not isinstance(chat, dict):
            continue
        sender_id = sender.get("id")
        if (
            type(sender_id) is int
            and 0 < sender_id < 2**52
            and sender.get("is_bot") is False
            and type(chat.get("id")) is int
            and chat["id"] == sender_id
            and chat.get("type") == "private"
            and type(message.get("date")) is int
            and message["date"] >= started - 60
            and not any(
                k in message for k in ("forward_origin", "forward_from", "via_bot", "sender_chat")
            )
        ):
            found.add(sender_id)
    if len(found) > 1:
        raise SetupError("More than one account answered. Restart setup with a fresh challenge")
    return next(iter(found), None)


def private_folder(root: Path) -> Path:
    folder = root / ".secrets"
    if folder.is_symlink() or not folder.is_dir():
        raise SetupError("Existing private .secrets directory is required")
    for name in ("telegram_bot_token", "telegram_config.json"):
        path = folder / name
        if path.exists() or path.is_symlink():
            raise SetupError("Telegram credential/config already exists; refusing to overwrite")
    return folder


def write_config(folder: Path, owner_id: UUID, sender_id: int, bot_id: int, token: str) -> None:
    values = {
        "telegram_bot_token": token.encode("ascii") + b"\n",
        "telegram_config.json": json.dumps(
            {"owner_id": str(owner_id), "sender_id": sender_id, "bot_id": bot_id}
        ).encode("ascii")
        + b"\n",
    }
    created = []
    try:
        for name, value in values.items():
            path = folder / name
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as file:
                created.append(path)
                file.write(value)
                file.flush()
                os.fsync(file.fileno())
            path.chmod(0o444)
    except OSError:
        for path in created:
            path.chmod(0o600)
            path.unlink()
        raise SetupError(
            "Could not save Telegram setup; existing credentials were not replaced"
        ) from None


def setup(root: Path, owner_id: UUID) -> None:
    folder = private_folder(root)
    if not sys.stdin.isatty():
        raise SetupError("Run setup interactively so the token can be entered without echo")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            token = getpass.getpass("Token BotFather (hidden): ").strip()
    except getpass.GetPassWarning:
        raise SetupError("Hidden token entry is unavailable; use an interactive terminal") from None
    if not re.fullmatch(r"[1-9][0-9]{0,15}:[A-Za-z0-9_-]{30,100}", token):
        raise SetupError("Invalid bot token format")
    me = call(token, "getMe", {})
    if (
        not isinstance(me, dict)
        or me.get("is_bot") is not True
        or type(me.get("id")) is not int
        or not 0 < me["id"] < 2**52
        or me["id"] != int(token.split(":", 1)[0])
        or not isinstance(me.get("username"), str)
        or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", me["username"])
    ):
        raise SetupError("Bot identity check failed")
    info = call(token, "getWebhookInfo", {})
    if not isinstance(info, dict) or info.get("url") != "":
        raise SetupError("Bot has an existing webhook. Use a new dedicated bot")
    challenge = "/jarvis_setup " + secrets.token_hex(12)
    started = time.time()
    print("Open your own bot @" + me["username"] + " in a PRIVATE chat.")
    print("Send this temporary setup challenge: " + challenge)
    input("After sending it, press Enter here: ")
    sender_id = None
    for _ in range(6):
        # No offset: discovery does not acknowledge/drop the existing update backlog.
        updates = call(
            token, "getUpdates", {"limit": 100, "timeout": 20, "allowed_updates": ["message"]}
        )
        sender_id = detect_sender(updates, challenge, started)
        if sender_id is not None:
            break
        time.sleep(1)
    if sender_id is None:
        raise SetupError("Challenge not found; use a new dedicated bot and retry setup")
    print("Detected numeric Telegram ID: " + str(sender_id))
    if input("Type that numeric ID again to bind this account: ").strip() != str(sender_id):
        raise SetupError("Account confirmation did not match; no files written")
    private_folder(root)
    write_config(folder, owner_id, sender_id, me["id"], token)
    print(json.dumps({"status": "telegram_configured", "secret_values_printed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set up a dedicated owner-private Telegram bot")
    parser.add_argument("--owner-id", type=UUID, required=True)
    args = parser.parse_args()
    try:
        setup(Path(__file__).resolve().parents[1], args.owner_id)
    except (SetupError, EOFError, KeyboardInterrupt) as error:
        message = str(error) if isinstance(error, SetupError) else "Setup cancelled"
        print(json.dumps({"status": "stopped", "reason": message}), file=sys.stderr)
        raise SystemExit(2) from None
