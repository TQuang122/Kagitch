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
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / ".config" / "kagitch")
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".config" / "kagitch" / "accounts.json")
    monkeypatch.setattr(cfg, "KAGGLE_DEFAULT", tmp_path / ".kaggle")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    # Create a fake kaggle.json for add tests
    kaggle_json = tmp_path / "kaggle.json"
    kaggle_json.write_text('{"username":"test","key":"abc123"}')
    return tmp_path, kaggle_json


def run_cli(*args, capsys) -> tuple[int, str]:
    """Run CLI with args, return (returncode, stdout)."""
    with patch.object(sys, "argv", ["kagitch"] + list(args)):
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
        assert "export KAGGLE_CONFIG_DIR=" in out

    def test_switch_default_account(self, temp_env, capsys):
        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        rc, out = run_cli("1", capsys=capsys)
        assert rc == 0
        assert "unset KAGGLE_CONFIG_DIR" in out

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
        assert "export KAGGLE_CONFIG_DIR=" in out

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
        assert "export" in out or "unset" in out


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
            assert "v1.0.0" in out

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
        assert "v1.0.0" in out


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
        rc_file.write_text('# kagitch shell integration v1.0.0\neval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.cli.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.cli.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)

        config = cfg.load_config()
        config["accounts"] = {
            "1": {"name": "alpha", "config_dir": "alpha"},
            "2": {"name": "beta", "config_dir": "beta"},
        }
        cfg.save_config(config)

        # Ensure .kaggle dir exists
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 0
        assert "Kaggle CLI" in out
        assert "Shell wrapper" in out
        assert "Shell version" in out
        assert "v1.0.0" in out
        assert "alpha" in out
        assert "beta" in out
        assert "Accounts" in out

    def test_doctor_no_accounts(self, temp_env, capsys, monkeypatch):
        """doctor handles no accounts gracefully."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('')
        monkeypatch.setattr("kaggle_switch.cli.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.cli.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: None)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 1
        assert "not found" in out
        assert "not installed" in out
        assert "No accounts" in out

    def test_doctor_stale_wrapper(self, temp_env, capsys, monkeypatch):
        """doctor warns when rc file has outdated version marker."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('# kagitch shell integration v0.9.0\neval "$(kagitch shellpath zsh)"\n')
        monkeypatch.setattr("kaggle_switch.cli.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.cli.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/kaggle" if x == "kaggle" else None)

        config = cfg.load_config()
        config["accounts"] = {"1": {"name": "alpha", "config_dir": ""}}
        cfg.save_config(config)
        kaggle_dir = tmp_path / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 1  # stale wrapper sets non-zero
        assert "outdated" in out
        assert "source" in out
        assert "kagitch init -r" in out

    def test_doctor_suggests_init(self, temp_env, capsys, monkeypatch):
        """doctor suggests init when no wrapper in rc file."""
        tmp_path, _ = temp_env
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text('')
        monkeypatch.setattr("kaggle_switch.cli.detect_shell", lambda: "zsh")
        monkeypatch.setattr("kaggle_switch.cli.rc_file_for_shell", lambda s: rc_file)
        monkeypatch.setattr("shutil.which", lambda x: None)

        rc, out = run_cli("doctor", capsys=capsys)
        assert rc == 1
        assert "kagitch init" in out
