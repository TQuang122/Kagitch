"""Tests for config module."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from kaggle_switch import config as cfg


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Patch config paths to use temp directory."""
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / ".config" / "kagitch")
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".config" / "kagitch" / "accounts.json")
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

    def test_load_empty_when_empty_file(self, temp_config):
        cfg.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg.CONFIG_FILE.write_text("")
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
        if sys.platform != "win32":
            assert oct(target.stat().st_mode)[-3:] == "600"

    def test_add_with_token_string(self, temp_config):
        config = {"accounts": {}}
        acc = cfg.add_account(config, "tokenuser", "KGAT_7b42f4050e6bed91ef395d02a0b3dc6d")
        assert acc.number == "1"
        assert acc.name == "tokenuser"
        target = temp_config / ".kaggle-tokenuser" / "access_token"
        assert target.exists()
        content = target.read_text().strip()
        assert content == "KGAT_7b42f4050e6bed91ef395d02a0b3dc6d"
        if sys.platform != "win32":
            assert oct(target.stat().st_mode)[-3:] == "600"

    def test_add_with_access_token_file(self, temp_config, tmp_path):
        token_file = tmp_path / "access_token"
        token_file.write_text("KGAT_abc123\n")
        config = {"accounts": {}}
        acc = cfg.add_account(config, "fileuser", token_file)
        assert acc.number == "1"
        assert acc.name == "fileuser"
        target = temp_config / ".kaggle-fileuser" / "access_token"
        assert target.exists()
        assert target.read_text().strip() == "KGAT_abc123"

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
        assert config["accounts"] == {"1": {"name": "b", "config_dir": "b"}}

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


class TestAuthType:
    def test_get_accounts_includes_auth_type(self, temp_config):
        config = {"accounts": {"1": {"name": "oauthuser", "config_dir": "oauthuser", "auth_type": "oauth"}}}
        accounts = cfg.get_accounts(config)
        assert accounts[0].auth_type == "oauth"

    def test_find_account_includes_auth_type(self, temp_config):
        config = {"accounts": {"1": {"name": "oauthuser", "config_dir": "oauthuser", "auth_type": "oauth"}}}
        acc = cfg.find_account(config, "1")
        assert acc is not None
        assert acc.auth_type == "oauth"

    def test_add_account_stores_auth_type(self, temp_config, tmp_path):
        json_file = tmp_path / "kaggle.json"
        json_file.write_text('{"username":"test","key":"abc"}')
        config = {"accounts": {}}
        acc = cfg.add_account(config, "oauthuser", json_file, auth_type="oauth")
        assert acc.auth_type == "oauth"
        assert config["accounts"]["1"]["auth_type"] == "oauth"

    def test_default_auth_type_empty(self, temp_config):
        config = {"accounts": {"1": {"name": "plain", "config_dir": "plain"}}}
        acc = cfg.get_accounts(config)[0]
        assert acc.auth_type == ""


class TestConfigDir:
    def test_posix_path(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        result = cfg._config_dir()
        assert ".config/kagitch" in str(result)

    def test_windows_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
        result = cfg._config_dir()
        assert "AppData/Roaming/kagitch" in str(result) or "AppData\\Roaming\\kagitch" in str(result)


class TestMigratePlaintextTokens:
    def test_migrate_moves_tokens_to_keychain(self, temp_config, monkeypatch):
        monkeypatch.setattr(cfg, "CONFIG_FILE", temp_config / "config" / "accounts.json")
        from kaggle_switch import keychain as kc
        monkeypatch.setattr(kc, "KEYRING_AVAILABLE", True)
        config = {"accounts": {"1": {"name": "alice", "api_token": "KGAT_secret1"}, "2": {"name": "bob", "api_token": "KGAT_secret2"}}}
        with patch("kaggle_switch.keychain.keyring") as mock_kring:
            cfg._migrate_plaintext_tokens(config)
        assert "api_token" not in config["accounts"]["1"]
        assert "api_token" not in config["accounts"]["2"]
        mock_kring.set_password.assert_any_call("kagitch", "alice", "KGAT_secret1")
        mock_kring.set_password.assert_any_call("kagitch", "bob", "KGAT_secret2")

    def test_migrate_skips_when_no_tokens(self, temp_config):
        config = {"accounts": {"1": {"name": "alice", "config_dir": "alice"}}}
        cfg._migrate_plaintext_tokens(config)
        assert "api_token" not in config["accounts"]["1"]


class TestGetToken:
    def test_returns_keychain_token(self, temp_config, monkeypatch):
        from kaggle_switch import keychain as kc
        monkeypatch.setattr(kc, "KEYRING_AVAILABLE", True)
        acc = cfg.Account(number="1", name="alice", config_dir="alice")
        with patch("kaggle_switch.keychain.keyring") as mock_kring:
            mock_kring.get_password.return_value = "KGAT_from_keychain"
            result = cfg.get_token(acc)
        assert result == "KGAT_from_keychain"

    def test_falls_back_to_account_field(self, temp_config, monkeypatch):
        from kaggle_switch import keychain as kc
        monkeypatch.setattr(kc, "KEYRING_AVAILABLE", True)
        acc = cfg.Account(number="1", name="alice", config_dir="alice", api_token="KGAT_fallback")
        with patch("kaggle_switch.keychain.keyring") as mock_kring:
            mock_kring.get_password.return_value = None
            result = cfg.get_token(acc)
        assert result == "KGAT_fallback"


class TestAddAccountEdgeCases:
    def test_add_with_renamed_file(self, temp_config, tmp_path, monkeypatch):
        """Config line 192: src.name not kaggle.json or access_token -> rename message."""
        some_file = tmp_path / "mycreds.txt"
        some_file.write_text('{"username":"test","key":"abc123"}')
        config = {"accounts": {}}
        with patch("sys.stderr") as mock_stderr:
            acc = cfg.add_account(config, "renameuser", some_file)
        assert acc.number == "1"
        target = temp_config / ".kaggle-renameuser" / "kaggle.json"
        assert target.exists()


class TestRemoveAccountEdgeCases:
    def test_remove_deletes_account_dir(self, temp_config):
        """Config line 214: shutil.rmtree called when account dir exists."""
        acc_dir = temp_config / ".kaggle-removeme"
        acc_dir.mkdir(parents=True)
        (acc_dir / "kaggle.json").write_text("{}")
        config = {"accounts": {"1": {"name": "removeme", "config_dir": "removeme"}}}
        acc = cfg.remove_account(config, "1")
        assert not acc_dir.exists()
        assert "1" not in config["accounts"]

