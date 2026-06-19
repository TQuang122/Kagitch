"""Tests for CLI module."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from kaggle_switch import cli
from kaggle_switch import config as cfg


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    """Patch all path dependencies to temp directory."""
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / ".config" / "kaggle-switch")
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".config" / "kaggle-switch" / "accounts.json")
    monkeypatch.setattr(cfg, "KAGGLE_DEFAULT", tmp_path / ".kaggle")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    # Create a fake kaggle.json for add tests
    kaggle_json = tmp_path / "fake_kaggle.json"
    kaggle_json.write_text('{"username":"test","key":"abc123"}')
    return tmp_path, kaggle_json


def run_cli(*args, capsys) -> tuple[int, str]:
    """Run CLI with args, return (returncode, stdout)."""
    with patch.object(sys, "argv", ["kaggle-switch"] + list(args)):
        rc = cli.main()
    captured = capsys.readouterr()
    return rc, captured.out + captured.err


class TestList:
    def test_no_accounts_message(self, temp_env, capsys):
        rc, out = run_cli(capsys=capsys)
        assert rc == 1
        assert "No accounts configured" in out

    def test_list_shows_accounts(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": ""},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        cfg.save_config(config)
        rc, out = run_cli("list", capsys=capsys)
        assert rc == 0
        assert "alpha" in out
        assert "beta" in out
        assert "1" in out
        assert "2" in out


class TestCurrent:
    def test_current_default(self, temp_env, capsys, monkeypatch):
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        rc, out = run_cli("current", capsys=capsys)
        assert rc == 0
        assert "alpha" in out


class TestSwitch:
    def test_switch_existing(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}, "2": {"name": "beta", "config_dir": "beta"}}
        cfg.save_config(config)
        rc, out = run_cli("2", capsys=capsys)
        assert rc == 0
        assert "__KAGGLE_SWITCH__" in out

    def test_switch_default_account(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        rc, out = run_cli("1", capsys=capsys)
        assert rc == 0
        assert out.strip() == "__KAGGLE_SWITCH__"

    def test_switch_not_found(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        rc, out = run_cli("99", capsys=capsys)
        assert rc == 1
        assert "not found" in out

    def test_switch_explicit_subcommand(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}, "2": {"name": "beta", "config_dir": "beta"}}
        cfg.save_config(config)
        rc, out = run_cli("switch", "2", capsys=capsys)
        assert rc == 0
        assert "__KAGGLE_SWITCH__" in out


class TestAdd:
    def test_add_with_json_path(self, temp_env, capsys):
        tmp_path, kaggle_json = temp_env
        rc, out = run_cli("add", "newuser", str(kaggle_json), capsys=capsys)
        assert rc == 0
        assert "Added account #1" in out
        assert "newuser" in out
        target = tmp_path / ".kaggle-newuser" / "kaggle.json"
        assert target.exists()

    def test_add_duplicate_fails(self, temp_env, capsys):
        tmp_path, kaggle_json = temp_env
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "dup", "config_dir": "dup"}}
        cfg.save_config(config)
        rc, out = run_cli("add", "dup", str(kaggle_json), capsys=capsys)
        assert rc == 1
        assert "already exists" in out

    def test_add_missing_json_path_fails(self, temp_env, capsys):
        rc, out = run_cli("add", "newuser", "/nonexistent/path.json", capsys=capsys)
        assert rc == 1
        assert "not found" in out.lower() or "no such" in out.lower()


class TestRemove:
    def test_remove_cancelled(self, temp_env, capsys, monkeypatch):
        import io
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
        rc, out = run_cli("remove", "1", capsys=capsys)
        assert "Cancelled" in out
        # Account should still exist
        config = cfg.load_config()
        assert "1" in config["accounts"]


class TestRename:
    def test_rename_success(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "old", "config_dir": "old"}}
        cfg.save_config(config)
        rc, out = run_cli("rename", "1", "newname", capsys=capsys)
        assert rc == 0
        assert "newname" in out
        config = cfg.load_config()
        assert config["accounts"]["1"]["name"] == "newname"


class TestShellpath:
    def test_shellpath_zsh(self, temp_env, capsys):
        rc, out = run_cli("shellpath", "zsh", capsys=capsys)
        assert rc == 0
        assert "kaggle-switch()" in out

    def test_shellpath_fish(self, temp_env, capsys):
        rc, out = run_cli("shellpath", "fish", capsys=capsys)
        assert rc == 0
        assert "function kaggle-switch" in out

    def test_shellpath_invalid(self, temp_env, capsys):
        rc, out = run_cli("shellpath", "powershell", capsys=capsys)
        assert rc == 1
        assert "Unsupported" in out


class TestVersion:
    def test_version_flag(self, temp_env, capsys):
        rc, out = run_cli("--version", capsys=capsys)
        assert rc == 0
        assert "kaggle-switch" in out
        assert "1.0.0" in out


class TestHelp:
    def test_help_flag(self, temp_env, capsys):
        rc, out = run_cli("--help", capsys=capsys)
        assert rc == 0
        assert "Usage" in out
        assert "kaggle-switch" in out


class TestUnknownCommand:
    def test_unknown_returns_error(self, temp_env, capsys):
        rc, out = run_cli("foobar", capsys=capsys)
        assert rc == 1
        assert "Unknown command" in out
