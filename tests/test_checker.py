"""Tests for checker module."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from kaggle_switch.checker import check_account, check_all_accounts, CheckResult
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
        acc = Account(number="4", name="nokaggle", config_dir="nokaggle")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = FileNotFoundError("kaggle not found")
            result = check_account(acc)

        assert result.quota_ok is False
        assert "kaggle not found" in result.quota_error

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
