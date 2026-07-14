"""Tests for CLI module."""
from __future__ import annotations

import json
import os
import re
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from kaggle_switch import cli
from kaggle_switch import config as cfg
from kaggle_switch.commands import accounts as accounts_cmd
from kaggle_switch.commands.kernel import _kernel_style


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    """Patch all path dependencies to temp directory."""
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / ".config" / "kagitch")
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".config" / "kagitch" / "accounts.json")
    monkeypatch.setattr(cfg, "KAGGLE_DEFAULT", tmp_path / ".kaggle")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    kaggle_json = tmp_path / "kaggle.json"
    kaggle_json.write_text('{"username":"test","key":"abc123"}')

    # _apply_account_env() directly mutates os.environ, bypassing
    # monkeypatch — save and restore these env vars explicitly.
    saved_kcd = os.environ.get("KAGGLE_CONFIG_DIR")
    saved_kat = os.environ.get("KAGGLE_API_TOKEN")

    yield tmp_path, kaggle_json

    if saved_kcd is None:
        os.environ.pop("KAGGLE_CONFIG_DIR", None)
    else:
        os.environ["KAGGLE_CONFIG_DIR"] = saved_kcd
    if saved_kat is None:
        os.environ.pop("KAGGLE_API_TOKEN", None)
    else:
        os.environ["KAGGLE_API_TOKEN"] = saved_kat


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def run_cli(*args, capsys) -> tuple[int, str]:
    """Run CLI with args, return (returncode, stdout)."""
    with patch.object(sys, "argv", ["kagitch"] + list(args)):
        rc = cli.main()
    captured = capsys.readouterr()
    return rc, _ANSI_RE.sub("", captured.out + captured.err)


class TestList:
    def test_no_accounts_message(self, temp_env, capsys):
        rc, out = run_cli(capsys=capsys)
        assert rc == 1
        assert "No accounts configured" in out

    def test_list_no_accounts_message(self, temp_env, capsys):
        rc, out = run_cli("list", capsys=capsys)
        assert rc == 1
        assert "No accounts configured" in out

    def test_bare_command_shows_dashboard(self, temp_env, capsys, monkeypatch):
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": ""},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        cfg.save_config(config)

        rc, out = run_cli(capsys=capsys)

        assert rc == 0
        assert "Dashboard" in out
        assert "Active" in out
        assert "alpha" in out
        assert "beta" in out
        assert "No creds" in out

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

    def test_current_stale_active_account(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": "alpha"}}
        cfg.save_config(config)

        with patch("kaggle_switch.commands.accounts.current_active", return_value="99"):
            rc, out = run_cli("current", capsys=capsys)

        assert rc == 1
        assert "Account 99 not found in config" in out

    def test_current_shell_wrapper_uses_tty_status(self, temp_env, capsys, monkeypatch):
        from kaggle_switch.checker import CheckResult

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)

        result = CheckResult(
            number="1",
            name="alpha",
            config_path=Path("/tmp/fake"),
            file_ok=True,
            auth_user="alpha",
            auth_match=True,
            quota_ok=True,
            gpu_remaining="4.00h",
            tpu_remaining="2.00h",
        )

        with patch("kaggle_switch.commands.accounts.display._tty_status", return_value=nullcontext()) as mock_status, \
             patch("kaggle_switch.checker.check_account", return_value=result) as mock_check:
            rc, out = run_cli("current", capsys=capsys)

        assert rc == 0
        assert "alpha" in out
        assert "4.00h" in out
        assert "2.00h" in out
        mock_status.assert_called_once()
        mock_check.assert_called_once()


class TestLogin:
    def test_login_missing_name(self, temp_env, capsys):
        rc, out = run_cli("login", capsys=capsys)
        assert rc == 1
        assert "Usage" in out

    def test_login_duplicate_name(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "existing", "config_dir": "existing"}}
        cfg.save_config(config)
        rc, out = run_cli("login", "existing", capsys=capsys)
        assert rc == 1
        assert "already exists" in out

    def test_add_via_oauth_duplicate_name(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "existing", "config_dir": "existing"}}
        cfg.save_config(config)

        rc = accounts_cmd._add_via_oauth(config, "existing")
        captured = capsys.readouterr()
        out = _ANSI_RE.sub("", captured.out + captured.err)

        assert rc == 1
        assert "Account 'existing' already exists as #1" in out

    def test_add_via_oauth_import_error(self, temp_env, capsys):
        config = cfg.load_config()

        original_import = __import__

        def fail_kagglesdk_import(name, *args, **kwargs):
            if name.startswith("kagglesdk"):
                raise ImportError("no sdk")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_kagglesdk_import):
            rc = accounts_cmd._add_via_oauth(config, "oauthuser")

        captured = capsys.readouterr()
        out = _ANSI_RE.sub("", captured.out + captured.err)

        assert rc == 1
        assert "kagglesdk is required for OAuth login" in out
        assert "pip install kagglesdk" in out

    def test_login_oauth_success(self, temp_env, capsys, monkeypatch):
        pytest.importorskip("kagglesdk")
        tmp_path, _ = temp_env

        class MockCreds:
            def get_username(self):
                return "kaggleuser"

        class MockOAuth:
            def authenticate(self, **kw):
                return MockCreds()

        monkeypatch.setattr("kagglesdk.kaggle_client.KaggleClient", object)
        monkeypatch.setattr("kagglesdk.kaggle_oauth.KaggleOAuth", lambda client: MockOAuth())

        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(parents=True, exist_ok=True)
        (kaggle_dir / "credentials.json").write_text('{"refresh_token": "rt1"}')

        rc, out = run_cli("login", "oauthuser", capsys=capsys)
        assert rc == 0
        assert "oauthuser" in out
        assert "kaggleuser" in out

        config = cfg.load_config()
        assert "1" in config["accounts"]
        assert config["accounts"]["1"]["auth_type"] == "oauth"
        assert config["accounts"]["1"]["name"] == "oauthuser"

        target = tmp_path / ".kaggle-oauthuser" / "credentials.json"
        assert target.exists()

    def test_login_oauth_failure(self, temp_env, capsys, monkeypatch):
        pytest.importorskip("kagglesdk")
        monkeypatch.setattr("kagglesdk.kaggle_client.KaggleClient", object)

        class FailingOAuth:
            def authenticate(self, **kw):
                raise Exception("Login failed")

        monkeypatch.setattr("kagglesdk.kaggle_oauth.KaggleOAuth", lambda client: FailingOAuth())

        rc, out = run_cli("login", "failuser", capsys=capsys)
        assert rc == 1
        assert "failed" in out.lower()


class TestSwitch:
    def test_switch_existing(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}, "2": {"name": "beta", "config_dir": "beta"}}
        cfg.save_config(config)
        rc, out = run_cli("2", capsys=capsys)
        assert rc == 0
        assert "Switched" in out
        assert "beta" in out
        assert "export KAGGLE_CONFIG_DIR=" not in out
        assert "unset KAGGLE_API_TOKEN" not in out

    def test_switch_wrapper_mode_emits_env_lines(self, temp_env, capsys, monkeypatch):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}, "2": {"name": "beta", "config_dir": "beta"}}
        cfg.save_config(config)
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        rc, out = run_cli("2", capsys=capsys)

        assert rc == 0
        assert "export KAGGLE_CONFIG_DIR=" in out
        assert "unset KAGGLE_API_TOKEN" in out
        assert "Switched" in out

    def test_switch_default_account(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        rc, out = run_cli("1", capsys=capsys)
        assert rc == 0
        assert "Switched" in out
        assert "unset KAGGLE_CONFIG_DIR" not in out

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
        assert "Switched" in out
        assert "export KAGGLE_CONFIG_DIR=" not in out

    def test_switch_without_arg_prompts_for_account(self, temp_env, capsys, monkeypatch):
        import io

        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": ""},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        cfg.save_config(config)
        monkeypatch.setattr("sys.stdin", io.StringIO("2\n"))

        rc, out = run_cli("switch", capsys=capsys)

        assert rc == 0
        assert "Select account" in out
        assert "beta" in out
        assert "Switched" in out
        assert "export KAGGLE_CONFIG_DIR=" not in out

    def test_switch_without_arg_rejects_invalid_choice(self, temp_env, capsys, monkeypatch):
        import io

        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": ""},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        cfg.save_config(config)
        monkeypatch.setattr("sys.stdin", io.StringIO("99\n"))

        rc, out = run_cli("switch", capsys=capsys)

        assert rc == 1
        assert "Invalid account" in out
        assert "Available" in out
        assert "Traceback" not in out

    def test_switch_to_oauth_copies_credentials_json(self, temp_env, capsys):
        tmp_path, _ = temp_env
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "legacy", "config_dir": ""},
            "2": {"name": "myoauth", "config_dir": "myoauth", "auth_type": "oauth"},
        }
        cfg.save_config(config)

        oauth_dir = tmp_path / ".kaggle-myoauth"
        oauth_dir.mkdir(parents=True, exist_ok=True)
        (oauth_dir / "credentials.json").write_text('{"refresh_token": "rt1"}')

        with patch("kaggle_switch.commands.switch._refresh_oauth_token", return_value=None):
            rc, out = run_cli("2", capsys=capsys)
        assert rc == 0

        dest = tmp_path / ".kaggle" / "credentials.json"
        assert dest.exists()
        assert "rt1" in dest.read_text()

    def test_switch_to_oauth_without_credentials_file(self, temp_env, capsys):
        """OAuth switch should not crash if credentials.json is missing."""
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "brokenoauth", "config_dir": "brokenoauth", "auth_type": "oauth"},
        }
        cfg.save_config(config)
        rc, out = run_cli("1", capsys=capsys)
        assert rc == 0
        assert "Switched" in out
        assert "Traceback" not in out


class TestAdd:
    def test_add_with_json_path(self, temp_env, capsys):
        tmp_path, kaggle_json = temp_env
        rc, out = run_cli("add", "newuser", str(kaggle_json), capsys=capsys)
        assert rc == 0
        assert "Added account #1" in out
        assert "newuser" in out
        target = tmp_path / ".kaggle-newuser" / kaggle_json.name
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

    def test_add_with_token(self, temp_env, capsys):
        tmp_path, _ = temp_env
        rc, out = run_cli("add", "tokenacc", "KGAT_7b42f4050e6bed91ef395d02a0b3dc6d", capsys=capsys)
        assert rc == 0
        assert "Added account #1" in out
        assert "tokenacc" in out
        target = tmp_path / ".kaggle-tokenacc" / "access_token"
        assert target.exists()
        assert target.read_text().strip() == "KGAT_7b42f4050e6bed91ef395d02a0b3dc6d"


class TestRemove:
    def test_remove_usage_without_arg(self, temp_env, capsys):
        rc, out = run_cli("remove", capsys=capsys)
        assert rc == 1
        assert "Usage: kagitch remove <N|name>" in out

    def test_remove_not_found(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        rc, out = run_cli("remove", "missing", capsys=capsys)

        assert rc == 1
        assert "Account 'missing' not found" in out

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

    def test_remove_confirmed(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        with patch("kaggle_switch.commands.accounts.Confirm.ask", return_value=True):
            rc, out = run_cli("remove", "1", capsys=capsys)

        assert rc == 0
        assert "Removed account #1" in out
        config = cfg.load_config()
        assert "1" not in config["accounts"]


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

    def test_rename_usage_without_args(self, temp_env, capsys):
        rc, out = run_cli("rename", "1", capsys=capsys)
        assert rc == 1
        assert "Usage: kagitch rename <N> <new_name>" in out

    def test_rename_not_found(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        rc, out = run_cli("rename", "99", "newname", capsys=capsys)

        assert rc == 1
        assert "Account #99 not found" in out


class TestAliases:
    def test_help_aliases(self, temp_env, capsys):
        for alias in ("-h", "help"):
            rc, out = run_cli(alias, capsys=capsys)
            assert rc == 0
            assert "Usage" in out

    def test_version_aliases(self, temp_env, capsys):
        for alias in ("-v", "version"):
            rc, out = run_cli(alias, capsys=capsys)
            assert rc == 0
            assert "v1.5.1" in out

    def test_list_alias(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        rc, out = run_cli("ls", capsys=capsys)
        assert rc == 0
        assert "alpha" in out

    def test_current_aliases(self, temp_env, capsys, monkeypatch):
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        for alias in ("cur", "."):
            rc, out = run_cli(alias, capsys=capsys)
            assert rc == 0
            assert "alpha" in out

    def test_remove_alias(self, temp_env, capsys, monkeypatch):
        import io

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
        rc, out = run_cli("rm", "1", capsys=capsys)
        assert rc == 0
        assert "Cancelled" in out



class TestShellpath:
    def test_shellpath_zsh(self, temp_env, capsys):
        rc, out = run_cli("shellpath", "zsh", capsys=capsys)
        assert rc == 0
        assert "kagitch()" in out

    def test_shellpath_fish(self, temp_env, capsys):
        rc, out = run_cli("shellpath", "fish", capsys=capsys)
        assert rc == 0
        assert "function kagitch" in out

    def test_shellpath_invalid(self, temp_env, capsys):
        rc, out = run_cli("shellpath", "tcsh", capsys=capsys)
        assert rc == 1
        assert "Unsupported" in out


class TestVersion:
    def test_version_flag(self, temp_env, capsys):
        rc, out = run_cli("--version", capsys=capsys)
        assert rc == 0
        assert "v1.5.1" in out


class TestHelp:
    def test_help_flag(self, temp_env, capsys):
        rc, out = run_cli("--help", capsys=capsys)
        assert rc == 0
        assert "Usage" in out
        assert "kagitch" in out


class TestUnknownCommand:
    def test_unknown_returns_error(self, temp_env, capsys):
        rc, out = run_cli("foobar", capsys=capsys)
        assert rc == 1
        assert "Unknown command" in out


class TestCheck:
    def test_check_with_accounts(self, temp_env, capsys):
        """check runs and produces table output."""
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": "alpha"},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        cfg.save_config(config)

        with patch("kaggle_switch.checker.check_all_accounts") as mock:
            from kaggle_switch.checker import CheckResult
            r1 = CheckResult(number="1", name="alpha",
                             config_path=temp_env[0] / ".kaggle-alpha")
            r1.file_ok = True
            r1.auth_match = True
            r1.quota_ok = True
            r1.gpu_remaining = "4.13h"
            r1.tpu_remaining = "20.00h"

            r2 = CheckResult(number="2", name="beta",
                             config_path=temp_env[0] / ".kaggle-beta")
            r2.file_ok = False
            r2.file_error = "missing kaggle.json"
            r2.quota_ok = False

            mock.return_value = [r1, r2]

            rc, out = run_cli("check", capsys=capsys)

        assert rc == 0
        assert "alpha" in out
        assert "beta" in out
        assert "4.13h" in out
        assert "\u2717 Failed" in out

    def test_check_no_accounts(self, temp_env, capsys):
        rc, out = run_cli("check", capsys=capsys)
        assert rc == 0

    def test_check_machine_mode(self, temp_env, capsys, monkeypatch):
        """check uses _tty_status when KAGITCH_SHELL_WRAPPER=1."""
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        from kaggle_switch.checker import CheckResult
        r1 = CheckResult(number="1", name="alpha", config_path=Path("/tmp/fake"))
        r1.file_ok = True
        r1.auth_match = True

        with patch("kaggle_switch.checker.check_all_accounts", return_value=[r1]):
            rc, out = run_cli("check", capsys=capsys)

        assert rc == 0

    def test_check_quota_errors(self, temp_env, capsys, monkeypatch):
        """check shows quota errors in table and summary."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        from kaggle_switch.checker import CheckResult
        r1 = CheckResult(number="1", name="alpha", config_path=Path("/tmp/fake"))
        r1.file_ok = True
        r1.auth_match = True
        r1.quota_ok = False
        r1.quota_error = "API rate limit"

        with patch("kaggle_switch.checker.check_all_accounts", return_value=[r1]):
            rc, out = run_cli("check", capsys=capsys)

        assert rc == 0
        assert "err" in out

    def test_check_legacy_count(self, temp_env, capsys, monkeypatch):
        """check shows legacy key warning in summary."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        from kaggle_switch.checker import CheckResult
        r1 = CheckResult(number="1", name="alpha", config_path=Path("/tmp/fake"))
        r1.file_ok = True
        r1.auth_match = True
        r1.auth_method = "LEGACY_API_KEY"
        r1.quota_ok = True
        r1.gpu_remaining = "4.00h"
        r1.tpu_remaining = "0h"

        with patch("kaggle_switch.checker.check_all_accounts", return_value=[r1]):
            rc, out = run_cli("check", capsys=capsys)

        assert rc == 0
        assert "Legacy Key" in out


class TestListAccounts:
    def test_list_accounts_output(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "first", "config_dir": ""},
            "2": {"name": "second", "config_dir": "second"},
        }
        cfg.save_config(config)

        rc, out = run_cli("__list_accounts", capsys=capsys)
        assert rc == 0
        assert "1:first" in out
        assert "2:second" in out

    def test_list_accounts_empty(self, temp_env, capsys):
        rc, out = run_cli("__list_accounts", capsys=capsys)
        assert rc == 0
        assert out.strip() == ""


class TestCompletions:
    def test_completions_zsh(self, temp_env, capsys):
        rc, out = run_cli("completions", "zsh", capsys=capsys)
        assert rc == 0
        assert "#compdef" in out

    def test_completions_bash(self, temp_env, capsys):
        rc, out = run_cli("completions", "bash", capsys=capsys)
        assert rc == 0
        assert "complete -F" in out

    def test_completions_fish(self, temp_env, capsys):
        rc, out = run_cli("completions", "fish", capsys=capsys)
        assert rc == 0
        assert "complete -c kagitch" in out

    def test_completions_invalid(self, temp_env, capsys):
        rc, out = run_cli("completions", "tcsh", capsys=capsys)
        assert rc == 1
        assert "Unsupported" in out


class TestDoctor:
    def test_doctor_basic(self, temp_env, capsys, monkeypatch):
        """doctor runs and shows all sections with accounts."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)

        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": "alpha"},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        cfg.save_config(config)

        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 0
        assert "Status:" in out
        assert "checks passed" in out
        assert "Kaggle CLI" in out
        assert "Shell wrapper" in out
        assert "Config dir" in out
        assert "alpha" in out
        assert "beta" in out
        assert "Accounts" in out

    def test_doctor_no_accounts(self, temp_env, capsys, monkeypatch):
        """doctor handles no accounts gracefully."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: None)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 1
        assert "not found" in out
        assert "not installed" in out
        assert "No accounts" in out

    def test_doctor_suggests_reload(self, temp_env, capsys, monkeypatch):
        """doctor shows reload hint when wrapper is installed."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 0
        assert "reload" in out and "wrapper" in out
        assert "kagitch init -r" in out

    def test_doctor_suggests_init(self, temp_env, capsys, monkeypatch):
        """doctor suggests init when no wrapper in rc file."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: None)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 1
        assert "kagitch init" in out

    def test_doctor_active_account_creds(self, temp_env, capsys, monkeypatch):
        """doctor shows active account, OAuth creds path, indicator, active tag."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)
        (kaggle_dir / "credentials.json").write_text("{}")

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 0
        assert "OAuth creds" in out
        assert "#1 alpha" in out
        assert "\u25ba" in out  # active indicator
        assert "OAuth" in out
        assert "active" in out

    def test_doctor_quota_ok_tty(self, temp_env, capsys, monkeypatch):
        """doctor shows quota OK lines via console.status (TTY mode)."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        from kaggle_switch.checker import CheckResult
        cr = CheckResult(number="1", name="alpha", config_path=kaggle_dir)
        cr.quota_ok = True
        cr.gpu_remaining = "4.13h"
        cr.tpu_remaining = "20.00h"

        with patch("kaggle_switch.checker.check_account", return_value=cr):
            rc, out = run_cli("doctor", capsys=capsys)

        assert rc == 0
        assert "GPU" in out
        assert "TPU" in out
        assert "4.13h" in out
        assert "20.00h" in out

    def test_doctor_quota_machine_mode(self, temp_env, capsys, monkeypatch):
        """doctor uses _tty_status when KAGITCH_SHELL_WRAPPER=1."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        from kaggle_switch.checker import CheckResult
        cr = CheckResult(number="1", name="alpha", config_path=kaggle_dir)
        cr.quota_ok = True
        cr.gpu_remaining = "2.00h"

        with patch("kaggle_switch.checker.check_account", return_value=cr):
            rc, out = run_cli("doctor", capsys=capsys)

        assert rc == 0
        assert "GPU" in out
        assert "2.00h" in out

    def test_doctor_quota_error(self, temp_env, capsys, monkeypatch):
        """doctor shows quota error when check_account returns error."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        from kaggle_switch.checker import CheckResult
        cr = CheckResult(number="1", name="alpha", config_path=kaggle_dir)
        cr.quota_ok = False
        cr.quota_error = "403 Forbidden"

        with patch("kaggle_switch.checker.check_account", return_value=cr):
            rc, out = run_cli("doctor", capsys=capsys)

        assert rc == 0
        assert "403 Forbidden" in out

    def test_doctor_quota_na(self, temp_env, capsys, monkeypatch):
        """doctor shows n/a when quota not OK and no error."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        from kaggle_switch.checker import CheckResult
        cr = CheckResult(number="1", name="alpha", config_path=kaggle_dir)
        cr.quota_ok = False

        with patch("kaggle_switch.checker.check_account", return_value=cr):
            rc, out = run_cli("doctor", capsys=capsys)

        assert rc == 0
        assert "n/a" in out

    def test_doctor_legacy_badge(self, temp_env, capsys, monkeypatch):
        """doctor shows Legacy Key badge for accounts with kaggle.json."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": "alpha"}}
        cfg.save_config(config)
        acc_path = tmp_path / ".kaggle-alpha"
        acc_path.mkdir(parents=True, exist_ok=True)
        (acc_path / "kaggle.json").write_text('{"username":"test","key":"abc123"}')

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 0
        assert "Legacy Key" in out

    def test_doctor_unknown_auth(self, temp_env, capsys, monkeypatch):
        """doctor shows ? for token auth method."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('eval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": "alpha"}}
        cfg.save_config(config)
        acc_path = tmp_path / ".kaggle-alpha"
        acc_path.mkdir(parents=True, exist_ok=True)
        (acc_path / "access_token").write_text("some-token")

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 0
        assert "? Token" in out

    def test_doctor_powershell_reload(self, temp_env, capsys, monkeypatch):
        """doctor shows . $PROFILE reload hint for powershell."""
        tmp_path, _ = temp_env
        ps_profile = tmp_path / "Microsoft.PowerShell_profile.ps1"
        ps_profile.write_text('kagitch shellpath powershell\n')
        monkeypatch.setattr("kaggle_switch.commands.doctor.detect_shell", lambda: "powershell")
        monkeypatch.setattr("kaggle_switch.commands.doctor.rc_file_for_shell", lambda s: ps_profile)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 0
        assert "source" not in out
        assert "kagitch init -r" in out

    def test_doctor_config_dir_unreadable(self, temp_env, capsys, monkeypatch):
        """doctor flags config dir when it exists but is not readable."""
        tmp_path, _ = temp_env
        config_dir = tmp_path / ".kaggle"
        config_dir.mkdir(exist_ok=True)
        original_access = os.access
        monkeypatch.setattr(
            os, "access",
            lambda path, mode, **kw: False if path == config_dir else original_access(path, mode, **kw),
        )
        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 1
        assert "not" in out and "readable" in out

    def test_doctor_creds_unreadable(self, temp_env, capsys, monkeypatch):
        """doctor flags OAuth creds when file exists but is not readable."""
        tmp_path, _ = temp_env
        config_dir = tmp_path / ".kaggle"
        config_dir.mkdir(exist_ok=True)
        creds_file = config_dir / "credentials.json"
        creds_file.write_text("{}")
        original_access = os.access
        monkeypatch.setattr(
            os, "access",
            lambda path, mode, **kw: False if str(path) == str(creds_file) else original_access(path, mode, **kw),
        )
        rc, out = run_cli("doctor", capsys=capsys)
        assert "readable" in out

    def test_doctor_kaggle_no_active(self, temp_env, capsys, monkeypatch):
        """doctor shows 'no active account' when kaggle installed but no account active."""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)
        rc, out = run_cli("doctor", capsys=capsys)
        assert "no active account" in out


class TestCurrentQuota:
    """Tests for cmd_current using check_account (single-account optimization)."""

    def test_current_shows_quota(self, temp_env, capsys, monkeypatch):
        """current calls check_account for the active account only."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        from kaggle_switch.checker import CheckResult
        cr = CheckResult(number="1", name="alpha", config_path=Path("/tmp/fake"))
        cr.quota_ok = True
        cr.gpu_remaining = "4.13h"
        cr.tpu_remaining = "20.00h"

        with patch("kaggle_switch.checker.check_account", return_value=cr):
            rc, out = run_cli("current", capsys=capsys)

        assert rc == 0
        assert "alpha" in out
        assert "4.13h" in out
        assert "20.00h" in out

    def test_current_shows_quota_error(self, temp_env, capsys, monkeypatch):
        """current shows quota error when check_account returns error."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        from kaggle_switch.checker import CheckResult
        cr = CheckResult(number="1", name="alpha", config_path=Path("/tmp/fake"))
        cr.quota_ok = False
        cr.quota_error = "403 Forbidden"

        with patch("kaggle_switch.checker.check_account", return_value=cr):
            rc, out = run_cli("current", capsys=capsys)

        assert rc == 0
        assert "403 Forbidden" in out

    def test_current_no_active(self, temp_env, capsys, monkeypatch):
        """current shows warning when no account is active."""
        # current_active returns None only when KAGGLE_CONFIG_DIR is set but
        # doesn't match any account's config_dir
        monkeypatch.setenv("KAGGLE_CONFIG_DIR", "/nonexistent/path")
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": "alpha"}}
        cfg.save_config(config)

        rc, out = run_cli("current", capsys=capsys)
        assert rc == 0
        assert "No account active" in out


class TestCheckSwitchRecommendation:
    """Tests for 'switch to best' recommendation in check summary."""

    def _make_check_result(self, number, name, gpu_remaining, quota_ok=True):
        from kaggle_switch.checker import CheckResult
        cr = CheckResult(number=number, name=name, config_path=Path("/tmp/fake"))
        cr.file_ok = True
        cr.auth_match = True
        cr.quota_ok = quota_ok
        cr.gpu_remaining = gpu_remaining
        cr.tpu_remaining = "0h"
        return cr

    def test_check_recommends_switch(self, temp_env, capsys, monkeypatch):
        """check suggests switching when another account has more GPU quota."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": ""},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        config["active"] = "1"
        cfg.save_config(config)

        r1 = self._make_check_result("1", "alpha", "1.00h")
        r2 = self._make_check_result("2", "beta", "4.00h")

        with patch("kaggle_switch.checker.check_all_accounts", return_value=[r1, r2]):
            rc, out = run_cli("check", capsys=capsys)

        assert rc == 0
        assert "Try" in out
        assert "kagitch 2" in out
        assert "more GPU quota" in out

    def test_check_no_recommendation_same_quota(self, temp_env, capsys, monkeypatch):
        """check does NOT recommend switch when active account already has best GPU."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": ""},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        config["active"] = "1"
        cfg.save_config(config)

        r1 = self._make_check_result("1", "alpha", "4.00h")
        r2 = self._make_check_result("2", "beta", "1.00h")

        with patch("kaggle_switch.checker.check_all_accounts", return_value=[r1, r2]):
            rc, out = run_cli("check", capsys=capsys)

        assert rc == 0
        assert "Try" not in out
        assert "more GPU quota" not in out

    def test_check_no_recommendation_when_no_active(self, temp_env, capsys, monkeypatch):
        """check does NOT recommend switch when no account is active."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": ""},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        cfg.save_config(config)

        r1 = self._make_check_result("1", "alpha", "1.00h")
        r2 = self._make_check_result("2", "beta", "4.00h")

        with patch("kaggle_switch.checker.check_all_accounts", return_value=[r1, r2]), \
             patch("kaggle_switch.commands.doctor.current_active", return_value=None):
            rc, out = run_cli("check", capsys=capsys)

        assert rc == 0
        assert "more GPU quota" not in out


class TestPatchError:
    """Tests for improved cmd_patch error message."""

    def test_patch_missing_file_suggests_init(self, temp_env, capsys, monkeypatch):
        """patch suggests kaggle kernels init when metadata file not found."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        config["active"] = "1"
        cfg.save_config(config)

        rc, out = run_cli("patch", str(temp_env[0] / "nonexistent"), capsys=capsys)
        assert rc == 1
        assert "kaggle kernels init" in out


class TestKernelInit:
    """Tests for kagitch kernel init."""

    def test_help_does_not_prompt(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init --help prints help without entering the wizard."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "kernel-metadata.json").write_text("{}")

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions, \
             patch("questionary.confirm") as mock_confirm:
            rc, out = run_cli("kernel", "init", "--help", capsys=capsys)

        assert rc == 0
        assert "Usage" in out
        assert "kagitch kernel init" in out
        mock_confirm.assert_not_called()
        mock_questions.assert_not_called()

    def test_select_highlight_tracks_pointer(self):
        """kernel init select style highlights the cursor row, not the default value."""
        style = _kernel_style()
        rules = dict(style.style_rules)

        assert "bg:ansigreen" in rules["highlighted"]
        assert "noinherit" in rules["selected"]
        assert "bg:" not in rules["selected"]
        # highlighted must be defined after selected so it takes precedence on cursor row
        slist = style.style_rules
        h_idx = next(i for i, (n, _) in enumerate(slist) if n == "highlighted")
        s_idx = next(i for i, (n, _) in enumerate(slist) if n == "selected")
        assert h_idx > s_idx

    def test_basic_creates_metadata(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init creates kernel-metadata.json with correct defaults."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        config["active"] = "1"
        cfg.save_config(config)

        (tmp_path / "train.py").write_text("print('hello')")
        monkeypatch.chdir(tmp_path)

        form_answers = {
            "title": "My Kernel",
            "slug": "my-kernel",
            "lang": "python",
            "ktype": "script",
            "code_path": "train.py",
            "is_private": True,
            "accelerator": "None",
            "enable_internet": True,
            "dataset_src": "",
            "comp_src": "",
            "kernel_src": "",
            "model_src": "",
        }

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_questions.return_value = form_answers
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 0
        meta_file = tmp_path / "kernel-metadata.json"
        assert meta_file.exists()
        import json
        meta = json.loads(meta_file.read_text())
        assert meta["title"] == "My Kernel"
        assert meta["slug"] if "slug" in meta else meta["id"].endswith("my-kernel")
        assert meta["language"] == "python"
        assert meta["kernel_type"] == "script"
        assert meta["code_file"] == "train.py"
        assert meta["enable_gpu"] == "false"
        assert meta["machine_shape"] == ""
        assert "enable_tpu" not in meta

    def test_auto_detect_ipynb(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init auto-detects language=python, type=notebook from .ipynb."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)

        (tmp_path / "analysis.ipynb").write_text("{}")
        monkeypatch.chdir(tmp_path)

        form_answers = {
            "title": "Analysis",
            "slug": "analysis",
            "lang": "python",
            "ktype": "notebook",
            "code_path": "analysis.ipynb",
            "is_private": True,
            "accelerator": "None",
            "enable_internet": True,
            "dataset_src": "",
            "comp_src": "",
            "kernel_src": "",
            "model_src": "",
        }

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_questions.return_value = form_answers
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 0
        import json
        meta = json.loads((tmp_path / "kernel-metadata.json").read_text())
        assert meta["language"] == "python"
        assert meta["kernel_type"] == "notebook"

    def test_overwrite_decline_aborts(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init aborts when user declines overwrite of existing file."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        (tmp_path / "kernel-metadata.json").write_text("{}")
        monkeypatch.chdir(tmp_path)

        with patch("questionary.confirm") as mock_confirm:
            mock_confirm.return_value.ask.return_value = False
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 0
        assert json.loads((tmp_path / "kernel-metadata.json").read_text()) == {}

    def test_overwrite_confirm_writes(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init overwrites when user confirms."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        (tmp_path / "kernel-metadata.json").write_text("{}")
        monkeypatch.chdir(tmp_path)

        (tmp_path / "test.py").write_text("x=1")

        form_answers = {
            "title": "Test",
            "slug": "test",
            "lang": "python",
            "ktype": "script",
            "code_path": "test.py",
            "is_private": True,
            "accelerator": "None",
            "enable_internet": True,
            "dataset_src": "",
            "comp_src": "",
            "kernel_src": "",
            "model_src": "",
        }

        with patch("questionary.confirm") as mock_confirm, \
             patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_confirm.return_value.ask.return_value = True
            mock_questions.return_value = form_answers
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 0
        meta = json.loads((tmp_path / "kernel-metadata.json").read_text())
        assert meta["title"] == "Test"

    def test_cancelled_by_user(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init handles Ctrl+C gracefully."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        monkeypatch.chdir(tmp_path)

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_questions.side_effect = KeyboardInterrupt
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 1
        assert "Cancelled" in out

    def test_empty_dict_cancelled(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init handles empty dict from cancelled form."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        monkeypatch.chdir(tmp_path)

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_questions.return_value = {}
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 1
        assert "Cancelled" in out

    def test_overwrite_then_form_empty(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init handles overwrite confirmed then empty form result."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        (tmp_path / "kernel-metadata.json").write_text("{}")
        (tmp_path / "test.py").write_text("x=1")
        monkeypatch.chdir(tmp_path)

        with patch("questionary.confirm") as mock_confirm, \
             patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_confirm.return_value.ask.return_value = True
            mock_questions.return_value = {}
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 1
        assert "Cancelled" in out

    def test_bad_usage(self, temp_env, capsys, monkeypatch):
        """kagitch kernel without init subcommand prints usage."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        rc, out = run_cli("kernel", capsys=capsys)
        assert rc == 1
        assert "Usage" in out

    def test_sources_comma_separated(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init parses comma-separated sources."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        monkeypatch.chdir(tmp_path)
        (tmp_path / "notebook.py").write_text("x=1")

        form_answers = {
            "title": "Test",
            "slug": "test",
            "lang": "python",
            "ktype": "script",
            "code_path": "notebook.py",
            "is_private": True,
            "accelerator": "NvidiaTeslaT4",
            "enable_internet": True,
            "dataset_src": "user/dataset1, user/dataset2",
            "comp_src": "competition/titanic",
            "kernel_src": "",
            "model_src": "org/model1",
        }

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_questions.return_value = form_answers
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 0
        meta = json.loads((tmp_path / "kernel-metadata.json").read_text())
        assert meta["dataset_sources"] == ["user/dataset1", "user/dataset2"]
        assert meta["competition_sources"] == ["competition/titanic"]
        assert meta["kernel_sources"] == []
        assert meta["model_sources"] == ["org/model1"]
        assert meta["enable_gpu"] == "true"
        assert meta["machine_shape"] == "NvidiaTeslaT4"
        assert "enable_tpu" not in meta

    def test_tpu_uses_machine_shape_without_enable_tpu(
        self, temp_env, capsys, monkeypatch, tmp_path
    ):
        """kernel init stores TPU selection in machine_shape only."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        monkeypatch.chdir(tmp_path)
        (tmp_path / "train.py").write_text("x=1")

        form_answers = {
            "title": "TPU Test",
            "slug": "tpu-test",
            "lang": "python",
            "ktype": "script",
            "code_path": "train.py",
            "is_private": True,
            "accelerator": "Tpu1VmV38",
            "enable_internet": True,
            "dataset_src": "",
            "comp_src": "",
            "kernel_src": "",
            "model_src": "",
        }

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_questions.return_value = form_answers
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 0
        meta = json.loads((tmp_path / "kernel-metadata.json").read_text())
        assert meta["enable_gpu"] == "false"
        assert meta["machine_shape"] == "Tpu1VmV38"
        assert "enable_tpu" not in meta

    def test_no_active_username(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init uses slug-only id when no active username."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        monkeypatch.chdir(tmp_path)
        (tmp_path / "train.py").write_text("x=1")

        form_answers = {
            "title": "Test",
            "slug": "my-kern",
            "lang": "python",
            "ktype": "script",
            "code_path": "train.py",
            "is_private": True,
            "accelerator": "None",
            "enable_internet": True,
            "dataset_src": "",
            "comp_src": "",
            "kernel_src": "",
            "model_src": "",
        }

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions, \
             patch("kaggle_switch.commands.kernel._active_username", return_value=None):
            mock_questions.return_value = form_answers
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 0
        meta = json.loads((tmp_path / "kernel-metadata.json").read_text())
        assert meta["id"] == "my-kern"

    def test_no_code_file_fails(self, temp_env, capsys, monkeypatch, tmp_path):
        """kernel init fails when user clears the code file prompt."""
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        config = cfg.load_config()
        cfg.save_config(config)

        monkeypatch.chdir(tmp_path)

        form_answers = {
            "title": "Test",
            "slug": "test",
            "lang": "python",
            "ktype": "script",
            "code_path": "",
            "is_private": True,
            "accelerator": "None",
            "enable_internet": True,
            "dataset_src": "",
            "comp_src": "",
            "kernel_src": "",
            "model_src": "",
        }

        with patch("kaggle_switch.commands.kernel._ask_kernel_init_questions") as mock_questions:
            mock_questions.return_value = form_answers
            rc, out = run_cli("kernel", "init", capsys=capsys)

        assert rc == 1
        assert "required" in out.lower()


class TestCliCoverage:
    """Cover remaining cli.py dispatch lines: cmd_init, cmd_update, kernel logs, main exception."""

    def test_init_dispatch(self, temp_env, capsys):
        """Line 89: kagitch init calls cmd_init (no args = wizard)."""
        with patch("kaggle_switch.cli.cmd_init", return_value=0):
            rc, out = run_cli("init", capsys=capsys)
        assert rc == 0

    def test_init_reload(self, temp_env, capsys):
        """Line 89: kagitch init -r calls cmd_init(['-r'])."""
        with patch("kaggle_switch.cli.cmd_init", return_value=0):
            rc, out = run_cli("init", "-r", capsys=capsys)
        assert rc == 0

    def test_update_dispatch(self, temp_env, capsys, monkeypatch):
        """Line 95: kagitch update calls cmd_update()."""
        with patch("kaggle_switch.cli.cmd_update", return_value=0):
            rc, out = run_cli("update", capsys=capsys)
        assert rc == 0

    def test_kernel_logs_dispatch(self, temp_env, capsys, monkeypatch):
        """Line 107: kagitch kernel logs <name> calls cmd_kernel_logs."""
        with patch("kaggle_switch.cli.cmd_kernel_logs", return_value=0):
            rc, out = run_cli("kernel", "logs", "mykernel", capsys=capsys)
        assert rc == 0

    def test_main_exception_handler(self, temp_env, capsys):
        """Lines 37-40: main() catches _main() exceptions and returns 1."""
        with patch("kaggle_switch.cli._main", side_effect=ValueError("boom")):
            rc, out = run_cli(capsys=capsys)
        assert rc == 1
        assert "Traceback" in out


class TestMainBlock:
    """Tests for __name__ == '__main__' guard (line 130)."""

    def test_main_block_executes(self, monkeypatch):
        """Line 130: sys.exit(main()) runs when __name__ == '__main__'."""
        import runpy

        monkeypatch.setattr(sys, "argv", ["kagitch", "--help"])
        monkeypatch.delitem(sys.modules, "kaggle_switch.cli", raising=False)
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("kaggle_switch.cli", run_name="__main__")
        assert exc.value.code == 0
