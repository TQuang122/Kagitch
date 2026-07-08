"""Tests for init_wizard.py — interactive setup wizard."""
from __future__ import annotations

import json
from collections import namedtuple
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

    def test_python_old_and_git_missing(self, capcon, monkeypatch):
        VersionInfo = namedtuple("VersionInfo", "major minor micro")
        monkeypatch.setattr(iw.sys, "version_info", VersionInfo(3, 7, 9))

        def which_side(cmd):
            if cmd == "kaggle":
                return "/usr/bin/kaggle"
            if cmd == "git":
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

    def test_filters_registered_dirs_and_non_dirs(self, capcon):
        config = {
            "accounts": {
                "1": {"name": "work", "config_dir": "work", "auth_type": "oauth"},
            }
        }
        with patch.object(
            iw,
            "_scan_filesystem_dirs",
            return_value=[(".kaggle-work", True), (".kaggle-personal", False)],
        ):
            _, unreg = iw._step_account_scan(capcon, config)
        assert unreg == [(".kaggle-personal", False)]


class TestStepAddAccounts:
    def test_declined(self, capcon):
        config = {"accounts": {}}
        with patch.object(iw.Confirm, "ask", return_value=False):
            result = iw._step_add_accounts(capcon, config)
        assert result is False

    def test_empty_name_then_token_success(self, capcon):
        config = {"accounts": {}}
        prompts = iter(["", "new", "token", "abc123"])

        def ask_side(*args, **kwargs):
            return next(prompts)

        with patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw.Prompt, "ask", side_effect=ask_side), \
             patch("kaggle_switch.config.add_account") as mock_add, \
             patch.object(iw, "save_config") as mock_save:
            result = iw._step_add_accounts(capcon, config)

        assert result is True
        mock_add.assert_called_once_with(config, "new", "abc123", auth_type="token")
        mock_save.assert_called_once_with(config)

    def test_duplicate_name_then_token_success(self, capcon):
        config = {"accounts": {"1": {"name": "work", "config_dir": "work", "auth_type": "oauth"}}}
        prompts = iter(["work", "personal", "token", "secret"])

        def ask_side(*args, **kwargs):
            return next(prompts)

        with patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw.Prompt, "ask", side_effect=ask_side), \
             patch("kaggle_switch.config.add_account") as mock_add, \
             patch.object(iw, "save_config") as mock_save:
            result = iw._step_add_accounts(capcon, config)

        assert result is True
        mock_add.assert_called_once_with(config, "personal", "secret", auth_type="token")
        mock_save.assert_called_once_with(config)

    def test_token_empty(self, capcon):
        config = {"accounts": {}}
        prompts = iter(["new", "token", "   "])

        with patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw.Prompt, "ask", side_effect=lambda *a, **kw: next(prompts)), \
             patch.object(iw, "save_config") as mock_save:
            result = iw._step_add_accounts(capcon, config)

        assert result is False
        mock_save.assert_not_called()

    def test_oauth_success(self, capcon):
        config = {"accounts": {}}
        prompts = iter(["new", "oauth"])

        with patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw.Prompt, "ask", side_effect=lambda *a, **kw: next(prompts)), \
             patch("kaggle_switch.commands.accounts._add_via_oauth", return_value=1):
            result = iw._step_add_accounts(capcon, config)

        assert result is True

    def test_oauth_returns_false(self, capcon):
        config = {"accounts": {}}
        prompts = iter(["new", "oauth"])

        with patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw.Prompt, "ask", side_effect=lambda *a, **kw: next(prompts)), \
             patch("kaggle_switch.commands.accounts._add_via_oauth", return_value=0):
            result = iw._step_add_accounts(capcon, config)

        assert result is False

    def test_oauth_exception(self, capcon):
        config = {"accounts": {}}
        prompts = iter(["new", "oauth"])

        with patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw.Prompt, "ask", side_effect=lambda *a, **kw: next(prompts)), \
             patch("kaggle_switch.commands.accounts._add_via_oauth", side_effect=RuntimeError("boom")):
            result = iw._step_add_accounts(capcon, config)

        assert result is False

    def test_legacy_missing_file(self, capcon):
        config = {"accounts": {}}
        prompts = iter(["new", "legacy", "/missing/file.json"])

        with patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw.Prompt, "ask", side_effect=lambda *a, **kw: next(prompts)):
            result = iw._step_add_accounts(capcon, config)

        assert result is False

    def test_legacy_add_account_error(self, capcon, tmp_path):
        config = {"accounts": {}}
        legacy = tmp_path / "kaggle.json"
        legacy.write_text("{}")
        prompts = iter(["new", "legacy", str(legacy)])

        with patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw.Prompt, "ask", side_effect=lambda *a, **kw: next(prompts)), \
             patch("kaggle_switch.config.add_account", side_effect=ValueError("bad creds")):
            result = iw._step_add_accounts(capcon, config)

        assert result is False


class TestShellIntegration:
    def test_already_installed_reload_yes(self, capcon):
        with patch.object(iw, "_has_shell_integration", return_value=True), \
             patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw, "_reload_shell") as mock_reload:
            result = iw._step_shell_integration(capcon)
        assert result is True
        mock_reload.assert_called_once_with(capcon)

    def test_already_installed_reload_no(self, capcon):
        with patch.object(iw, "_has_shell_integration", return_value=True), \
             patch.object(iw.Confirm, "ask", return_value=False), \
             patch.object(iw, "_reload_shell") as mock_reload:
            result = iw._step_shell_integration(capcon)
        assert result is True
        mock_reload.assert_not_called()

    def test_install_declined(self, capcon):
        with patch.object(iw, "_has_shell_integration", return_value=False), \
             patch.object(iw.Confirm, "ask", return_value=False):
            result = iw._step_shell_integration(capcon)
        assert result is False

    def test_rc_none(self, capcon):
        with patch.object(iw, "_has_shell_integration", return_value=False), \
             patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw, "detect_shell", return_value="mystery"), \
             patch.object(iw, "rc_file_for_shell", return_value=None):
            result = iw._step_shell_integration(capcon)
        assert result is False

    def test_already_present_in_rc(self, capcon, tmp_path):
        rc = tmp_path / ".zshrc"
        rc.write_text("source <(kagitch shellpath zsh)\n")
        with patch.object(iw, "_has_shell_integration", return_value=False), \
             patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw, "detect_shell", return_value="zsh"), \
             patch.object(iw, "rc_file_for_shell", return_value=rc):
            result = iw._step_shell_integration(capcon)
        assert result is True

    def test_fresh_install_appends_and_reloads(self, capcon, tmp_path):
        rc = tmp_path / ".zshrc"
        with patch.object(iw, "_has_shell_integration", return_value=False), \
             patch.object(iw.Confirm, "ask", return_value=True), \
             patch.object(iw, "detect_shell", return_value="zsh"), \
             patch.object(iw, "rc_file_for_shell", return_value=rc), \
             patch.object(iw, "eval_line_for_shell", return_value="eval-contents"), \
             patch.object(iw, "_reload_shell") as mock_reload:
            result = iw._step_shell_integration(capcon)
        assert result is True
        assert "kagitch shell integration" in rc.read_text()
        assert "eval-contents" in rc.read_text()
        mock_reload.assert_called_once_with(capcon)


class TestReloadShell:
    def test_powershell_with_rc(self, capcon, tmp_path):
        rc = tmp_path / "profile.ps1"
        with patch.object(iw, "detect_shell", return_value="powershell"), \
             patch.object(iw, "rc_file_for_shell", return_value=rc):
            iw._reload_shell(capcon)

    def test_powershell_without_rc(self, capcon):
        with patch.object(iw, "detect_shell", return_value="powershell"), \
             patch.object(iw, "rc_file_for_shell", return_value=None):
            iw._reload_shell(capcon)

    def test_posix_with_rc(self, capcon, tmp_path):
        rc = tmp_path / ".zshrc"
        with patch.object(iw, "detect_shell", return_value="zsh"), \
             patch.object(iw, "rc_file_for_shell", return_value=rc):
            iw._reload_shell(capcon)

    def test_posix_without_rc(self, capcon):
        with patch.object(iw, "detect_shell", return_value="zsh"), \
             patch.object(iw, "rc_file_for_shell", return_value=None):
            iw._reload_shell(capcon)


class TestProjectSetup:
    def test_no_metadata(self, capcon):
        with patch.object(iw, "_detect_kernel_metadata", return_value=None):
            result = iw._step_project_setup(capcon, {"accounts": {}})
        assert result is False

    def test_no_active_username(self, capcon, tmp_path):
        km = tmp_path / "kernel-metadata.json"
        km.write_text('{"id": "bob/notebook"}')
        with patch.object(iw, "_detect_kernel_metadata", return_value=km), \
             patch("kaggle_switch.commands.kernel._active_username", return_value=None):
            result = iw._step_project_setup(capcon, {"accounts": {}})
        assert result is False

    def test_already_correct_owner(self, capcon, tmp_path):
        km = tmp_path / "kernel-metadata.json"
        km.write_text('{"id": "alice/notebook"}')
        with patch.object(iw, "_detect_kernel_metadata", return_value=km), \
             patch("kaggle_switch.commands.kernel._active_username", return_value="alice"):
            result = iw._step_project_setup(capcon, {"accounts": {}})
        assert result is True

    def test_owner_diff_decline_patch(self, capcon, tmp_path):
        km = tmp_path / "kernel-metadata.json"
        km.write_text('{"id": "bob/notebook"}')
        with patch.object(iw, "_detect_kernel_metadata", return_value=km), \
             patch("kaggle_switch.commands.kernel._active_username", return_value="alice"), \
             patch.object(iw.Confirm, "ask", return_value=False):
            result = iw._step_project_setup(capcon, {"accounts": {}})
        assert result is False

    def test_owner_diff_patch_success(self, capcon, tmp_path):
        km = tmp_path / "kernel-metadata.json"
        km.write_text('{"id": "bob/notebook"}')
        with patch.object(iw, "_detect_kernel_metadata", return_value=km), \
             patch("kaggle_switch.commands.kernel._active_username", return_value="alice"), \
             patch.object(iw.Confirm, "ask", return_value=True), \
             patch("kaggle_switch.commands.kernel._auto_patch_metadata", return_value="bob/notebook -> alice/notebook"):
            result = iw._step_project_setup(capcon, {"accounts": {}})
        assert result is True

    def test_owner_diff_patch_failure(self, capcon, tmp_path):
        km = tmp_path / "kernel-metadata.json"
        km.write_text('{"id": "bob/notebook"}')
        with patch.object(iw, "_detect_kernel_metadata", return_value=km), \
             patch("kaggle_switch.commands.kernel._active_username", return_value="alice"), \
             patch.object(iw.Confirm, "ask", return_value=True), \
             patch("kaggle_switch.commands.kernel._auto_patch_metadata", return_value=None):
            result = iw._step_project_setup(capcon, {"accounts": {}})
        assert result is False

    def test_invalid_kernel_metadata_json(self, capcon, tmp_path):
        km = tmp_path / "kernel-metadata.json"
        km.write_text('{')
        with patch.object(iw, "_detect_kernel_metadata", return_value=km), \
             patch("kaggle_switch.commands.kernel._active_username", return_value="alice"):
            result = iw._step_project_setup(capcon, {"accounts": {}})
        assert result is False


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

    def test_reloads_config_after_account_added(self, monkeypatch):
        first = {"accounts": {}}
        second = {"accounts": {"1": {"name": "new", "config_dir": "new"}}}
        load_calls = iter([first, second])

        monkeypatch.setattr(iw, "load_config", lambda: next(load_calls))
        monkeypatch.setattr(iw, "_step_system", lambda con: True)
        monkeypatch.setattr(iw, "_step_account_scan", lambda con, config: ([], []))
        monkeypatch.setattr(iw, "_step_add_accounts", lambda con, config: True)
        monkeypatch.setattr(iw, "_step_health_check", lambda con, config: [])
        monkeypatch.setattr(iw, "_step_shell_integration", lambda con: False)
        monkeypatch.setattr(iw, "_step_project_setup", lambda con, config: False)
        monkeypatch.setattr(iw, "_step_summary", lambda con, a, b, c, d: None)

        con = Console(file=None, force_terminal=True)
        rc = iw.run_wizard(con)
        assert rc == 0
