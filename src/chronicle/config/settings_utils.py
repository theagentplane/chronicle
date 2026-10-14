"""Load the settings: code, then environment, then the config file (design section 9).

The config file is JSON, or TOML on Python 3.11 and newer, named by ``CHRONICLE_CONFIG`` or
passed as ``config_file=``. Keys are the setting names; a dotted name such as
``hooks.fail_call_on_error`` may be written as a nested table.
"""

import importlib
import json
import os
from collections.abc import Mapping
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

from chronicle.config.config_enums import OverflowPolicy, TraceRegistration
from chronicle.config.settings_types import ChronicleSettings
from chronicle.framework.redaction.secret_redactors import default_redactors

ENV_PREFIX = "CHRONICLE_"
CONFIG_FILE_ENV = "CHRONICLE_CONFIG"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_CODE_ONLY = {"redactors"}
"""Settings that hold callables and so cannot come from the environment or a file."""


def load_settings(
    overrides: Mapping[str, Any] | None = None, config_file: str | Path | None = None
) -> ChronicleSettings:
    """Return the settings with precedence ``overrides`` > environment > config file."""
    values: dict[str, Any] = {}
    path = config_file or os.environ.get(CONFIG_FILE_ENV)
    if path:
        values.update(_read_file(Path(path)))
    values.update(_read_env(os.environ))
    values.update(overrides or {})
    return _build(values)


def is_recording_enabled(overrides: Mapping[str, Any] | None = None) -> bool:
    """Whether recording is on (``CHRONICLE_ENABLED`` and ``configure(enabled=...)``)."""
    return load_settings(overrides).enabled


def effective_redactors(settings: ChronicleSettings) -> tuple[Any, ...]:
    """The redactors to apply: the defaults if opted in, then the developer's own."""
    base = tuple(default_redactors()) if settings.default_redactors else ()
    return (*base, *settings.redactors)


def _build(values: Mapping[str, Any]) -> ChronicleSettings:
    known = {f.name: f for f in fields(ChronicleSettings)}
    flat = _flatten(values)
    kwargs: dict[str, Any] = {}
    for key, raw in flat.items():
        name = key.replace(".", "_")
        if name not in known:
            raise ValueError(f"unknown Chronicle setting {key!r}")
        kwargs[name] = _coerce(name, raw)
    return replace(ChronicleSettings(), **kwargs)


def _flatten(values: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in values.items():
        full = f"{prefix}{key}"
        if isinstance(value, Mapping) and full == "hooks":
            flat.update(_flatten(value, "hooks."))
        else:
            flat[full] = value
    return flat


def _coerce(name: str, raw: Any) -> Any:
    if name == "on_overflow":
        return raw if isinstance(raw, OverflowPolicy) else OverflowPolicy(str(raw).lower())
    if name == "trace_registration":
        return raw if isinstance(raw, TraceRegistration) else TraceRegistration(str(raw).lower())
    if name in ("inject_hosts",):
        if isinstance(raw, str):
            return tuple(part.strip() for part in raw.split(",") if part.strip())
        return tuple(raw)
    if name == "redactors":
        return tuple(raw)
    if isinstance(raw, str):
        return _coerce_text(name, raw)
    return raw


def _coerce_text(name: str, raw: str) -> Any:
    default = getattr(ChronicleSettings(), name)
    text = raw.strip()
    if isinstance(default, bool):
        lowered = text.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(f"setting {name!r} expects a boolean, got {raw!r}")
    if name == "max_payload_bytes":
        return int(text)
    if isinstance(default, int):
        return int(text)
    if isinstance(default, float):
        return float(text)
    return text


def _read_env(environ: Mapping[str, str]) -> dict[str, Any]:
    known = {f.name for f in fields(ChronicleSettings)} - _CODE_ONLY
    values: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(ENV_PREFIX) or key == CONFIG_FILE_ENV:
            continue
        name = key[len(ENV_PREFIX) :].lower()
        if name in known:
            values[name] = value
    return values


def _read_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".toml":
        try:
            tomllib = importlib.import_module("tomllib")
        except ModuleNotFoundError as exc:  # Python 3.10
            raise RuntimeError("TOML config files need Python 3.11 or newer; use JSON") from exc
        data = tomllib.loads(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} must hold an object")
    return {key: value for key, value in data.items() if key not in _CODE_ONLY}
