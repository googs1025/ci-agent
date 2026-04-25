"""Tests for TUI setup wizard logic."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_optimizer.tui.setup import mask_key, needs_setup


def test_needs_setup_no_config_file(tmp_path):
    with patch("ci_optimizer.tui.setup.CONFIG_FILE", tmp_path / "config.json"):
        assert needs_setup() is True


def test_needs_setup_config_exists(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"provider": "anthropic"}))
    with patch("ci_optimizer.tui.setup.CONFIG_FILE", config_file):
        assert needs_setup() is False


def test_mask_key_long():
    assert mask_key("sk-ant-api03-abcdefghij1234") == "sk-ant-a...1234"


def test_mask_key_short():
    assert mask_key("short") == "***"


def test_mask_key_none():
    assert mask_key(None) == "(未设置)"


def test_mask_key_empty():
    assert mask_key("") == "(未设置)"
