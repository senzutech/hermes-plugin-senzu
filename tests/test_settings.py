"""Settings per installation: read on every reply, changed from the command line."""

import sys
import types

import pytest
import senzu
from senzu import settings


@pytest.fixture
def config(monkeypatch):
    """A stand-in for hermes_cli.config, backed by a dict."""
    store: dict = {}

    def set_config_value(key, value, force=False):
        node = store
        *parents, leaf = key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value

    module = types.ModuleType("hermes_cli.config")
    module.load_config = lambda: store
    module.set_config_value = set_config_value
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", module)
    return store


def test_defaults_without_any_config(config):
    assert settings.current() == {"threshold": 6, "handover": "ask"}


def test_change_writes_only_what_it_is_given(config):
    assert settings.change(threshold=12) == {"threshold": 12, "handover": "ask"}
    assert settings.change(handover="auto")["threshold"] == 12


def test_out_of_range_is_refused_and_nothing_is_written(config):
    with pytest.raises(ValueError, match="between 3 and 50"):
        settings.change(threshold=2)
    assert settings.threshold() == 6


def test_a_garbled_value_in_config_falls_back_to_the_default(config):
    config.setdefault("plugins", {}).setdefault("entries", {})["senzu"] = {"threshold": "beaucoup"}
    assert settings.threshold() == 6


def test_a_higher_threshold_takes_effect_on_the_next_reply(config, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    settings.change(threshold=10)
    for _ in range(7):
        senzu.on_tool_result(tool_name="terminal", session_id="s", status="ok")
    assert senzu.on_reply(response_text="Je réessaie.", session_id="s") is None
    for _ in range(3):
        senzu.on_tool_result(tool_name="terminal", session_id="s", status="ok")
    assert "10 fois" in senzu.on_reply(response_text="Je réessaie.", session_id="s")
