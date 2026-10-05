"""Stdlib Windows/Linux wizard; only metadata GETs, never an inference POST."""

import getpass
import http.client
import json
import os
import re
import sys
import warnings
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID


class SetupError(RuntimeError):
    pass


def metadata(path: str, key: str):
    if path not in {"/api/v1/models", "/api/v1/endpoints/zdr"}:
        raise SetupError("Setup only allows public model/privacy metadata")
    connection = http.client.HTTPSConnection("openrouter.ai", timeout=30)
    try:
        connection.request(
            "GET", path, headers={"Authorization": "Bearer " + key, "Accept-Encoding": "identity"}
        )
        response = connection.getresponse()
        raw = response.read(8 * 1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 8 * 1024 * 1024:
            raise SetupError("Model metadata unavailable; no credentials saved")
        data = json.loads(raw).get("data")
        if not isinstance(data, list):
            raise ValueError
        return data
    except (OSError, http.client.HTTPException, ValueError, AttributeError):
        raise SetupError("Metadata check failed; no payload or credentials printed") from None
    finally:
        connection.close()


def free_candidates(models, endpoints):
    text_models = {
        m.get("id")
        for m in models
        if m.get("architecture", {}).get("output_modalities") == ["text"]
    }
    candidates = []
    for row in endpoints:
        model, provider = row.get("model_id", ""), row.get("tag", "")
        prices = row.get("pricing", {})
        if (
            model not in text_models
            or not model.endswith(":free")
            or row.get("status") != 0
            or "max_tokens" not in row.get("supported_parameters", [])
            or not {"prompt", "completion"}.issubset(prices)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.:-]{0,160}", model)
            or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{0,100}", provider)
        ):
            continue
        try:
            if any(Decimal(str(value)) != 0 for value in prices.values()):
                continue
        except (InvalidOperation, ValueError):
            continue
        candidates.append({"model": model, "provider": provider})
    return sorted(
        candidates,
        key=lambda r: (
            not r["model"].startswith(("qwen/", "deepseek/", "meta-llama/")),
            r["model"],
            r["provider"],
        ),
    )


def private_folder(root):
    folder = root / ".secrets"
    if not folder.is_dir() or folder.is_symlink():
        raise SetupError("Existing private .secrets folder required")
    for name in ("assistant_config.json", "openrouter_key"):
        if (folder / name).exists() or (folder / name).is_symlink():
            raise SetupError("Assistant setup exists; refusing to overwrite it")
    return folder


def write_config(folder, config, key):
    created = []
    try:
        for name, value in {
            "assistant_config.json": json.dumps(config, indent=2),
            "openrouter_key": key,
        }.items():
            path = folder / name
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as output:
                created.append(path)
                output.write(value.encode("ascii") + b"\n")
                output.flush()
                os.fsync(output.fileno())
            path.chmod(0o444)
    except OSError:
        for path in created:
            path.chmod(0o600)
            path.unlink()
        raise SetupError("Saving failed; existing credentials were preserved") from None


def setup(root):
    folder = private_folder(root)
    try:
        owner = str(UUID(json.loads((folder / "telegram_config.json").read_bytes())["owner_id"]))
    except (OSError, ValueError, KeyError, TypeError):
        raise SetupError("Valid existing Telegram config required") from None
    if not sys.stdin.isatty():
        raise SetupError("Run this wizard in an interactive terminal")
    print("/ask will send text, stored profile and selected history to OpenRouter/provider.")
    print("Do not send restricted documents or credentials through /ask.")
    print("In your OpenRouter account: disable prompt/output logging and training opt-in;")
    print(
        "enable ZDR for applicable model groups. Server request gates also enforce ZDR/no-training."
    )
    if input("After checking those account settings, type PRIVASI: ").strip() != "PRIVASI":
        raise SetupError("Account privacy settings not confirmed; no files written")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("OpenRouter API key (hidden): ").strip()
    except getpass.GetPassWarning:
        raise SetupError("Hidden entry unavailable; use an interactive terminal") from None
    if not 20 <= len(key) <= 512 or not key.isascii() or any(c.isspace() for c in key):
        raise SetupError("Invalid key format")
    candidates = free_candidates(
        metadata("/api/v1/models", key), metadata("/api/v1/endpoints/zdr", key)
    )
    if not candidates:
        raise SetupError(
            "No eligible free text endpoint in current catalog. No downgrade to paid/no-ZDR."
        )
    candidates = candidates[:10]
    for i, route in enumerate(candidates, 1):
        print(f"{i}. {route['model']} via {route['provider']}")
    answer = input("Choose a free route number [1]: ").strip() or "1"
    if not answer.isdigit() or not 1 <= int(answer) <= len(candidates):
        raise SetupError("Invalid route selection")
    config = {
        "owner_id": owner,
        "account_privacy_confirmed": True,
        "cloud_privacy": "no_training_zdr",
        "free_route": candidates[int(answer) - 1],
        "premium_route": None,
        "premium_mode": "confirm_each_use",
        "monthly_budget_usd": "0",
        "per_call_budget_usd": "0",
        "max_output_tokens": 512,
        "daily_free_calls": 15,
    }
    private_folder(root)
    write_config(folder, config, key)
    print(
        json.dumps(
            {
                "status": "assistant_configured",
                "premium_budget_usd": "0",
                "inference_sent": False,
                "secret_values_printed": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        setup(Path(__file__).resolve().parents[1])
    except (SetupError, EOFError, KeyboardInterrupt) as error:
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "reason": str(error) if isinstance(error, SetupError) else "Setup cancelled",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
