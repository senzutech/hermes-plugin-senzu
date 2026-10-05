"""Settings per installation: read on every reply, changed from the command line."""

import sys
import types

import pytest
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
    assert settings.current() == {"handover": "ask", "mood": "on"}


def test_change_writes_only_what_it_is_given(config):
    assert settings.change(handover="auto") == {"handover": "auto", "mood": "on"}
    assert settings.change(mood="off") == {"handover": "auto", "mood": "off"}


def test_an_unknown_value_is_refused_and_nothing_is_written(config):
    with pytest.raises(ValueError):
        settings.change(handover="sometimes")
    assert settings.mode() == "ask"


def test_a_setting_from_an_older_version_is_ignored(config):
    """``threshold`` meant something until 0.2.2; a config that still has it reads fine."""
    config.setdefault("plugins", {}).setdefault("entries", {})["senzu"] = {"threshold": "20"}
    assert settings.current() == {"handover": "ask", "mood": "on"}
