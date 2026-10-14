"""Configuration: code, then CHRONICLE_* environment, then the config file (design section 9)."""

import json
from pathlib import Path

import pytest

import chronicle
from chronicle.config import OverflowPolicy, TraceRegistration, load_settings


def test_defaults_match_the_design() -> None:
    settings = load_settings()
    assert settings.enabled is True
    assert settings.emit_open is False
    assert settings.default_redactors is False  # redaction is opt-in
    assert settings.inject_hosts == ()  # default deny
    assert settings.hooks_fail_call_on_error is False
    assert settings.fail_open is True
    assert settings.on_overflow is OverflowPolicy.DROP
    assert settings.trace_registration is TraceRegistration.SYNC


def test_environment_overrides_the_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "chronicle.json"
    config.write_text(json.dumps({"service_name": "from-file", "batch_size": 7}))
    monkeypatch.setenv("CHRONICLE_CONFIG", str(config))
    assert load_settings().service_name == "from-file"
    monkeypatch.setenv("CHRONICLE_SERVICE_NAME", "from-env")
    settings = load_settings()
    assert settings.service_name == "from-env"
    assert settings.batch_size == 7


def test_code_overrides_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHRONICLE_SERVICE_NAME", "from-env")
    chronicle.configure(service_name="from-code")
    assert chronicle.is_enabled() is True
    from chronicle.interfaces.runtime_utils import get_settings

    assert get_settings().service_name == "from-code"


def test_environment_values_are_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHRONICLE_ENABLED", "off")
    monkeypatch.setenv("CHRONICLE_INJECT_HOSTS", "a.internal, b.internal:8443")
    monkeypatch.setenv("CHRONICLE_HOOKS_FAIL_CALL_ON_ERROR", "true")
    monkeypatch.setenv("CHRONICLE_ON_OVERFLOW", "block")
    settings = load_settings()
    assert settings.enabled is False
    assert settings.inject_hosts == ("a.internal", "b.internal:8443")
    assert settings.hooks_fail_call_on_error is True
    assert settings.on_overflow is OverflowPolicy.BLOCK


def test_nested_hooks_table_in_a_file(tmp_path: Path) -> None:
    config = tmp_path / "chronicle.json"
    config.write_text(json.dumps({"hooks": {"fail_call_on_error": True}}))
    assert load_settings(config_file=config).hooks_fail_call_on_error is True


def test_unknown_setting_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown Chronicle setting"):
        chronicle.configure(no_such_setting=True)
