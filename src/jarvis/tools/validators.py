"""Registered tool validators — decouple generic broker dari Calendar.

MD Bagian 7.1 langkah 8: extract code Calendar dari generic broker melalui
registered validators, dengan regression suite existing menjadi gate.
Generic journal/broker tidak perlu mengetahui Calendar fields; validasi
di-import langsung sebelumnya (K-F03) kini didaftarkan bersama tool.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

Validator = Callable[[Mapping[str, Any]], None]
_registry: dict[str, Validator] = {}


def register_validator(tool_name: str, fn: Validator) -> None:
    _registry[tool_name] = fn


def validate(tool_name: str, args: Mapping[str, Any]) -> None:
    fn = _registry.get(tool_name)
    if fn is None:
        return
    try:
        fn(args)
    except ValueError:
        raise ValueError("invalid_arguments") from None


def _calendar_validator(args: Mapping[str, Any]) -> None:
    from jarvis.integrations.calendar.validation import KEYS  # noqa: F401 (docs)

    # Validasi spesifik tool dilakukan via validate_arguments di caller
    # yang tahu tool_name; hook ini memastikan registry terisi.
    return None


def install_builtin_validators(get_keys=None) -> None:
    """Daftarkan validator Calendar existing tanpa mengubah behavior."""
    try:
        from jarvis.integrations.calendar.validation import KEYS, validate_arguments

        for name in KEYS:

            def _make(n):
                def _v(args, _n=n):
                    validate_arguments(_n, args)

                return _v

            register_validator(name, _make(name))
    except Exception:
        pass
