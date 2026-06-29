"""Tests for init_wizard.py — interactive setup wizard."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

from kaggle_switch import init_wizard as iw


@pytest.fixture
def capcon():
    """Capture Rich console output."""
    return Console(file=None, force_terminal=True)


class TestCheckKaggleCli:
    """_check_kaggle_cli() helper."""

    def test_found(self):
        with patch("shutil.which", return_value="/usr/local/bin/kaggle"):
            found, path = iw._check_kaggle_cli()
        assert found is True
        assert path == "/usr/local/bin/kaggle"

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            found, path = iw._check_kaggle_cli()
        assert found is False
        assert path == ""


class TestScanFilesystemDirs:
    """_scan_filesystem_dirs() helper."""

    def test_finds_kaggle_dirs(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".kaggle-work").mkdir(parents=True)
        (home / ".kaggle-work" / "kaggle.json").write_text("{}")
        (home / ".kaggle-personal").mkdir(parents=True)
        # default .kaggle should be skipped
        (home / ".kaggle").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: home)

        result = iw._scan_filesystem_dirs()
        labels = [label for label, _ in result]
        assert ".kaggle-work" in labels
        assert ".kaggle-personal" in labels
        assert ".kaggle" not in labels

    def test_detects_credentials(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".kaggle-a").mkdir(parents=True)
        (home / ".kaggle-a" / "kaggle.json").write_text("{}")
        (home / ".kaggle-b").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: home)

        result = iw._scan_filesystem_dirs()
        creds = {label: has for label, has in result}
        assert creds[".kaggle-a"] is True
        assert creds[".kaggle-b"] is False

    def test_empty_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        assert iw._scan_filesystem_dirs() == []


class TestDetectKernelMetadata:
    """_detect_kernel_metadata() helper."""

    def test_finds_in_cwd(self, tmp_path):
        km = tmp_path / "kernel-metadata.json"
        km.write_text("{}")
        assert iw._detect_kernel_metadata(tmp_path) == km

    def test_finds_in_parent(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        km = tmp_path / "kernel-metadata.json"
        km.write_text("{}")
        assert iw._detect_kernel_metadata(subdir) == km

    def test_not_found(self, tmp_path):
        assert iw._detect_kernel_metadata(tmp_path) is None


class TestHasShellIntegration:
    """_has_shell_integration() helper."""

    def test_true_when_present(self, tmp_path, monkeypatch):
        rc = tmp_path / ".zshrc"
        rc.write_text("source <(kagitch shellpath zsh)\n")
        monkeypatch.setattr(iw, "detect_shell", lambda: "zsh")
        monkeypatch.setattr(iw, "rc_file_for_shell", lambda s: rc)
        assert iw._has_shell_integration() is True

    def test_false_when_no_rc(self, monkeypatch):
        monkeypatch.setattr(iw, "detect_shell", lambda: "zsh")
        monkeypatch.setattr(iw, "rc_file_for_shell", lambda s: None)
        assert iw._has_shell_integration() is False

    def test_false_when_not_in_rc(self, tmp_path, monkeypatch):
        rc = tmp_path / ".zshrc"
        rc.write_text("some other stuff\n")
        monkeypatch.setattr(iw, "detect_shell", lambda: "zsh")
        monkeypatch.setattr(iw, "rc_file_for_shell", lambda s: rc)
        assert iw._has_shell_integration() is False


class TestRenderAuthBadge:
    """_render_auth_badge() helper."""

    def test_oauth(self):
        badge = iw._render_auth_badge("oauth")
        assert "OAuth" in badge

    def test_token(self):
        badge = iw._render_auth_badge("token")
        assert "Token" in badge

    def test_legacy(self):
        badge = iw._render_auth_badge("legacy")
        assert "Legacy Key" in badge

    def test_unknown(self):
        badge = iw._render_auth_badge("unknown")
        assert "Legacy Key" in badge


class TestStepSystem:
    """_step_system() — always returns True."""

    def test_all_ok(self, capcon):
        with patch.object(iw.shutil, "which", side_effect=lambda cmd: f"/usr/bin/{cmd}"):
            result = iw._step_system(capcon)
        assert result is True

    def test_kaggle_missing(self, capcon):
        def which_side(cmd):
            if cmd == "kaggle":
                return None
            return f"/usr/bin/{cmd}"
        with patch.object(iw.shutil, "which", side_effect=which_side):
            result = iw._step_system(capcon)
        assert result is True


class TestStepAccountScan:
    """_step_account_scan() — shows accounts and scans filesystem."""

    def test_no_accounts(self, capcon):
        config = {"accounts": {}}
        with patch.object(iw, "_scan_filesystem_dirs", return_value=[]):
            accounts, unreg = iw._step_account_scan(capcon, config)
        assert accounts == []
        assert unreg == []

    def test_with_accounts(self, capcon):
        config = {
            "accounts": {
                "1": {"name": "work", "config_dir": "~/.kaggle-work", "auth_type": "oauth"},
            }
        }
        accounts, _ = iw._step_account_scan(capcon, config)
        assert len(accounts) == 1
        assert accounts[0].name == "work"


class TestStepHealthCheck:
    """_step_health_check() — runs checks on accounts."""

    def test_no_accounts(self, capcon):
        config = {"accounts": {}}
        result = iw._step_health_check(capcon, config)
        assert result == []

    def test_with_accounts(self, capcon):
        config = {"accounts": {"1": {"name": "work"}}}
        mock_result = MagicMock()
        mock_result.number = "1"
        mock_result.name = "work"
        mock_result.auth_method = "OAuth"
        mock_result.file_ok = True
        mock_result.auth_match = True
        mock_result.gpu_remaining = "1.00h"
        mock_result.quota_error = False

        with patch.object(iw, "check_all_accounts", return_value=[mock_result]):
            result = iw._step_health_check(capcon, config)
        assert len(result) == 1

    def test_check_failure(self, capcon):
        config = {"accounts": {"1": {"name": "work"}}}
        with patch.object(iw, "check_all_accounts", side_effect=RuntimeError("fail")):
            result = iw._step_health_check(capcon, config)
        assert result == []


class TestStepSummary:
    """_step_summary() — always prints without error."""

    def test_summary_all_no(self, capcon):
        iw._step_summary(capcon, False, [], False, False)

    def test_summary_all_yes(self, capcon):
        iw._step_summary(capcon, True, [MagicMock()], True, True)


class TestRunWizard:
    """run_wizard() — full wizard flow (skipped interactions)."""

    def test_returns_zero(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"accounts": {}}))
        monkeypatch.setattr(iw, "load_config", lambda: {"accounts": {}})

        # Skip all interactive prompts
        monkeypatch.setattr(iw.Confirm, "ask", lambda *a, **kw: False)
        monkeypatch.setattr(iw.Prompt, "ask", lambda *a, **kw: "skip")

        # Skip filesystem scan
        monkeypatch.setattr(iw, "_scan_filesystem_dirs", lambda: [])

        # Skip shell integration
        monkeypatch.setattr(iw, "_has_shell_integration", lambda: True)
        monkeypatch.setattr(iw, "detect_shell", lambda: "zsh")
        monkeypatch.setattr(iw, "rc_file_for_shell", lambda s: None)

        # Skip project setup
        monkeypatch.setattr(iw, "_detect_kernel_metadata", lambda: None)

        con = Console(file=None, force_terminal=True)
        rc = iw.run_wizard(con)
        assert rc == 0
