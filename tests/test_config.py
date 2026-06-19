"""Tests for config module."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kaggle_switch import config as cfg


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Patch config paths to use temp directory."""
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / ".config" / "kaggle-switch")
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".config" / "kaggle-switch" / "accounts.json")
    monkeypatch.setattr(cfg, "KAGGLE_DEFAULT", tmp_path / ".kaggle")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def make_config(config_dir, accounts):
    """Write a config file directly."""
    config_dir.mkdir(parents=True, exist_ok=True)
    data = {"accounts": accounts}
    (config_dir / "accounts.json").write_text(json.dumps(data))
    return data


class TestLoadSaveConfig:
    def test_load_empty_when_no_file(self, temp_config):
        result = cfg.load_config()
        assert result == {"accounts": {}}

    def test_save_creates_dir_and_file(self, temp_config):
        cfg.save_config({"accounts": {"1": {"name": "test", "config_dir": "test"}}})
        assert cfg.CONFIG_FILE.exists()
        loaded = cfg.load_config()
        assert "1" in loaded["accounts"]
        assert loaded["accounts"]["1"]["name"] == "test"

    def test_save_roundtrip(self, temp_config):
        original = {"accounts": {"1": {"name": "a", "config_dir": "a"}, "2": {"name": "b", "config_dir": "b"}}}
        cfg.save_config(original)
        loaded = cfg.load_config()
        assert loaded == original


class TestGetAccounts:
    def test_empty_config(self, temp_config):
        assert cfg.get_accounts({"accounts": {}}) == []

    def test_sorted_by_number(self, temp_config):
        config = {"accounts": {"3": {"name": "c", "config_dir": "c"}, "1": {"name": "a", "config_dir": "a"}, "2": {"name": "b", "config_dir": "b"}}}
        accounts = cfg.get_accounts(config)
        assert [a.number for a in accounts] == ["1", "2", "3"]
        assert [a.name for a in accounts] == ["a", "b", "c"]

    def test_default_account_path(self, temp_config):
        accounts = cfg.get_accounts({"accounts": {"1": {"name": "default", "config_dir": ""}}})
        assert accounts[0].path == temp_config / ".kaggle"
        assert accounts[0].is_default is True

    def test_non_default_account_path(self, temp_config):
        accounts = cfg.get_accounts({"accounts": {"2": {"name": "alt", "config_dir": "alt"}}})
        assert accounts[0].path == temp_config / ".kaggle-alt"
        assert accounts[0].is_default is False


class TestFindAccount:
    def test_find_by_number(self, temp_config):
        config = {"accounts": {"1": {"name": "alpha", "config_dir": "alpha"}}}
        acc = cfg.find_account(config, "1")
        assert acc is not None
        assert acc.name == "alpha"

    def test_find_by_name(self, temp_config):
        config = {"accounts": {"1": {"name": "alpha", "config_dir": "alpha"}}}
        acc = cfg.find_account(config, "alpha")
        assert acc is not None
        assert acc.number == "1"

    def test_not_found(self, temp_config):
        config = {"accounts": {"1": {"name": "alpha", "config_dir": "alpha"}}}
        assert cfg.find_account(config, "99") is None
        assert cfg.find_account(config, "nonexistent") is None


class TestCurrentActive:
    def test_default_when_no_env(self, temp_config, monkeypatch):
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = {"accounts": {"1": {"name": "a", "config_dir": ""}}}
        assert cfg.current_active(config) == "1"

    def test_matches_suffix(self, temp_config, monkeypatch):
        monkeypatch.setenv("KAGGLE_CONFIG_DIR", "/home/user/.kaggle-alt")
        config = {"accounts": {"1": {"name": "a", "config_dir": ""}, "2": {"name": "alt", "config_dir": "alt"}}}
        assert cfg.current_active(config) == "2"

    def test_no_match_returns_none(self, temp_config, monkeypatch):
        monkeypatch.setenv("KAGGLE_CONFIG_DIR", "/some/random/path")
        config = {"accounts": {"1": {"name": "a", "config_dir": ""}}}
        assert cfg.current_active(config) is None


class TestAddAccount:
    def test_add_with_json_path(self, temp_config, tmp_path):
        # Create a fake kaggle.json
        json_file = tmp_path / "kaggle.json"
        json_file.write_text('{"username":"test","key":"abc123"}')

        config = {"accounts": {}}
        acc = cfg.add_account(config, "testuser", json_file)
        assert acc.number == "1"
        assert acc.name == "testuser"
        assert acc.config_dir == "testuser"
        target = temp_config / ".kaggle-testuser" / "kaggle.json"
        assert target.exists()
        assert oct(target.stat().st_mode)[-3:] == "600"

    def test_add_duplicate_name_raises(self, temp_config):
        config = {"accounts": {"1": {"name": "test", "config_dir": "test"}}}
        with pytest.raises(ValueError, match="already exists"):
            cfg.add_account(config, "test")

    def test_add_without_json_missing_dir_raises(self, temp_config):
        config = {"accounts": {}}
        with pytest.raises(FileNotFoundError):
            cfg.add_account(config, "nonexistent")

    def test_add_second_account_gets_number_2(self, temp_config, tmp_path):
        json_file = tmp_path / "kaggle.json"
        json_file.write_text('{"username":"test","key":"abc"}')
        config = {"accounts": {"1": {"name": "first", "config_dir": "first"}}}
        acc = cfg.add_account(config, "second", json_file)
        assert acc.number == "2"


class TestRemoveAccount:
    def test_remove_by_number(self, temp_config):
        config = {"accounts": {"1": {"name": "a", "config_dir": "a"}, "2": {"name": "b", "config_dir": "b"}}}
        acc = cfg.remove_account(config, "1")
        assert acc.name == "a"
        assert "1" not in config["accounts"]
        assert "2" in config["accounts"]

    def test_remove_by_name(self, temp_config):
        config = {"accounts": {"1": {"name": "alpha", "config_dir": "alpha"}}}
        acc = cfg.remove_account(config, "alpha")
        assert acc.number == "1"
        assert "1" not in config["accounts"]

    def test_remove_not_found_raises(self, temp_config):
        config = {"accounts": {}}
        with pytest.raises(KeyError, match="not found"):
            cfg.remove_account(config, "99")


class TestRenameAccount:
    def test_rename_by_number(self, temp_config):
        config = {"accounts": {"1": {"name": "old", "config_dir": "old"}}}
        acc = cfg.rename_account(config, "1", "new")
        assert acc.name == "new"
        assert config["accounts"]["1"]["name"] == "new"

    def test_rename_not_found(self, temp_config):
        config = {"accounts": {}}
        with pytest.raises(KeyError, match="not found"):
            cfg.rename_account(config, "99", "new")


class TestSwitchMarker:
    def test_default_account_marker(self, temp_config):
        acc = cfg.Account(number="1", name="default", config_dir="")
        assert cfg.switch_marker(acc) == "__KAGGLE_SWITCH__"

    def test_non_default_marker_includes_path(self, temp_config):
        acc = cfg.Account(number="2", name="alt", config_dir="alt")
        marker = cfg.switch_marker(acc)
        assert marker.startswith("__KAGGLE_SWITCH__")
        assert marker != "__KAGGLE_SWITCH__"
        assert "alt" in marker
