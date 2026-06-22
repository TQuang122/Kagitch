"""Tests for checker module."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from kaggle_switch.checker import _build_env, check_account, check_all_accounts, CheckResult
from kaggle_switch.config import Account


def make_config(tmp_path, accounts_data: dict) -> dict:
    config = {"accounts": {}}
    for num, (name, config_dir) in accounts_data.items():
        config["accounts"][num] = {"name": name, "config_dir": config_dir}
    return config


def fake_subprocess_config_view(**kwargs):
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="- username: testuser\n- auth_method: LEGACY_API_KEY\n"
    )


def fake_subprocess_quota(**kwargs):
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="""Competitions    Kernels    Datasets     Disk     GPU        TPU
...              ...        ...          ...     25.87h    20.00h
GPU       25.87h  4.13h      30.00h  ...
TPU       20.00h  0.00h      20.00h  ...
"""
    )


class TestCheckAccount:
    def test_valid_account(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-testuser"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text('{"username":"testuser","key":"abc"}')

        acc = Account(number="1", name="testuser", config_dir="testuser")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [fake_subprocess_config_view(), fake_subprocess_quota()]
            result = check_account(acc)

        assert result.file_ok is True
        assert result.file_error == ""
        assert result.auth_user == "testuser"
        assert result.auth_match is True
        assert result.quota_ok is True
        assert result.gpu_remaining == "4.13h"
        assert result.tpu_remaining == "0.00h"

    def test_missing_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="2", name="nonexistent", config_dir="nonexistent")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.return_value = fake_subprocess_config_view()
            result = check_account(acc)

        assert result.file_ok is False
        assert "no credentials" in result.file_error

    def test_auth_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-mismatch"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text('{"username":"other","key":"abc"}')

        acc = Account(number="3", name="mismatch", config_dir="mismatch")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_ok is True
        assert result.auth_user == "testuser"
        assert result.auth_match is False

    def test_kaggle_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.checker.shutil.which", lambda _: None)
        acc = Account(number="4", name="nokaggle", config_dir="nokaggle")

        result = check_account(acc)

        assert result.quota_ok is False
        assert "kaggle CLI not found on PATH" in result.quota_error

    def test_token_account_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-tokenacc"
        acc_path.mkdir(parents=True)
        (acc_path / "access_token").write_text("KGAT_7b42f4050e6bed91ef395d02a0b3dc6d\n")

        acc = Account(number="5", name="tokenacc", config_dir="tokenacc")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_ok is True

    def test_oauth_account_no_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-oauth"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text("{}")

        acc = Account(number="5", name="oauth", config_dir="oauth")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_ok is True


class TestCheckAllAccounts:
    def test_multiple_accounts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        for name in ("alpha", "beta"):
            p = tmp_path / f".kaggle-{name}"
            p.mkdir(parents=True)
            (p / "kaggle.json").write_text(json.dumps({"username": name, "key": "x"}))

        config = make_config(tmp_path, {
            "1": ("alpha", "alpha"),
            "2": ("beta", "beta"),
        })

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            results = check_all_accounts(config, max_workers=1)

        assert len(results) == 2
        assert results[0].number == "1"
        assert results[1].number == "2"
        assert all(r.quota_ok for r in results)

    def test_empty_config(self, tmp_path):
        config = {"accounts": {}}
        results = check_all_accounts(config)
        assert results == []


class TestBuildEnv:
    """_build_env must isolate the kaggle subprocess from shell env leakage."""

    def test_strips_kaggle_api_token(self, monkeypatch):
        """KAGGLE_API_TOKEN set by `kagitch switch` in parent shell must NOT
        leak into the subprocess env, otherwise kaggle CLI 2.2+ uses it for
        every account and bypasses per-account credential isolation."""
        monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_stale_token_from_switch")
        acc = Account(number="1", name="a", config_dir="a")
        env = _build_env(acc)
        assert "KAGGLE_API_TOKEN" not in env

    def test_sets_kaggle_config_dir_for_non_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        acc_path = tmp_path / ".kaggle-testuser"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text('{"username":"testuser","key":"k"}')

        acc = Account(number="1", name="testuser", config_dir="testuser")
        env = _build_env(acc)
        assert env.get("KAGGLE_CONFIG_DIR") == str(acc_path)

    def test_clears_kaggle_config_dir_for_default(self, monkeypatch, tmp_path):
        """Default account must NOT inherit KAGGLE_CONFIG_DIR from shell —
        it would point at another account's directory and confuse kaggle CLI."""
        monkeypatch.setenv("KAGGLE_CONFIG_DIR", "/some/other/account/dir")
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".kaggle").mkdir(parents=True)

        acc = Account(number="1", name="default", config_dir="")
        env = _build_env(acc)
        assert "KAGGLE_CONFIG_DIR" not in env

    def test_does_not_drop_unrelated_env_vars(self, monkeypatch):
        """Sanity check: the strip only targets KAGGLE_API_TOKEN,
        other env vars must still pass through."""
        monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_x")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setenv("HOME", "/home/user")

        acc = Account(number="1", name="a", config_dir="a")
        env = _build_env(acc)
        assert env.get("PATH") == "/usr/bin:/bin"
        assert env.get("HOME") == "/home/user"
        assert "KAGGLE_API_TOKEN" not in env
