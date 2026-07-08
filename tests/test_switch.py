"""Direct tests for switch module internals (not through CLI dispatch)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from kaggle_switch.commands.switch import (
    _active_username_from_account,
    _apply_account_env,
    _refresh_oauth_token,
    _wrapper_console,
    cmd_switch,
    cmd_switch_prompt,
)
from kaggle_switch.config import Account, load_config, save_config


# ── _refresh_oauth_token ────────────────────────────────────────


class TestRefreshOauthToken:
    def test_missing_creds_path(self, tmp_path):
        """Line 30-31: return None when credentials.json does not exist."""
        missing = tmp_path / "no-such-file.json"
        assert _refresh_oauth_token(missing) is None

    def test_kaggle_creds_load_none(self, tmp_path):
        """Line 38-39: return None when KaggleCredentials.load() returns None."""
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text("{}")

        with patch(
            "kagglesdk.kaggle_creds.KaggleCredentials"
        ) as MockCreds:
            MockCreds.load.return_value = None
            result = _refresh_oauth_token(creds_file)

        assert result is None

    def test_returns_access_token(self, tmp_path):
        """Happy path: creds.get_access_token() returns a token."""
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text("{}")

        with patch(
            "kagglesdk.kaggle_creds.KaggleCredentials"
        ) as MockCreds:
            fake_creds = MagicMock()
            fake_creds.get_access_token.return_value = "tok_abc"
            MockCreds.load.return_value = fake_creds
            result = _refresh_oauth_token(creds_file)

        assert result == "tok_abc"

    def test_exception_caught(self, tmp_path):
        """Line 41-42: broad Exception returns None."""
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text("{}")

        with patch(
            "kagglesdk.kaggle_client.KaggleClient"
        ) as MockClient:
            MockClient.side_effect = RuntimeError("boom")
            result = _refresh_oauth_token(creds_file)

        assert result is None


# ── _apply_account_env ──────────────────────────────────────────


class TestApplyAccountEnv:
    def test_default_clears_config_dir(self, monkeypatch):
        """Default account: pop KAGGLE_CONFIG_DIR."""
        monkeypatch.setenv("KAGGLE_CONFIG_DIR", "/some/path")
        monkeypatch.setenv("KAGGLE_API_TOKEN", "oldtok")
        acc = Account(number="1", name="default", config_dir="")
        with patch("kaggle_switch.commands.switch.get_token", return_value=""):
            _apply_account_env(acc)
        assert "KAGGLE_CONFIG_DIR" not in os.environ
        assert "KAGGLE_API_TOKEN" not in os.environ

    def test_non_default_sets_config_dir(self, monkeypatch):
        """Non-default account: set KAGGLE_CONFIG_DIR."""
        acc = Account(number="2", name="myacc", config_dir="myacc")
        expected = str(Path.home() / ".kaggle-myacc")
        with patch("kaggle_switch.commands.switch.get_token", return_value=""):
            _apply_account_env(acc)
        assert os.environ["KAGGLE_CONFIG_DIR"] == expected

    def test_sets_api_token(self, monkeypatch):
        """Line 56: set KAGGLE_API_TOKEN when token is available."""
        acc = Account(number="1", name="default", config_dir="")
        with patch("kaggle_switch.commands.switch.get_token", return_value="tok_secret"):
            _apply_account_env(acc)
        assert os.environ["KAGGLE_API_TOKEN"] == "tok_secret"

    def test_clears_api_token_when_empty(self, monkeypatch):
        """Line 58: pop KAGGLE_API_TOKEN when no token."""
        monkeypatch.setenv("KAGGLE_API_TOKEN", "stale")
        acc = Account(number="1", name="default", config_dir="")
        with patch("kaggle_switch.commands.switch.get_token", return_value=""):
            _apply_account_env(acc)
        assert "KAGGLE_API_TOKEN" not in os.environ

    def test_oauth_token_refresh(self, monkeypatch):
        """Line 53-54: when no token and oauth, calls _refresh_oauth_token."""
        acc = Account(number="1", name="myoauth", config_dir="myoauth", auth_type="oauth")
        with patch(
            "kaggle_switch.commands.switch.get_token", return_value=""
        ), patch(
            "kaggle_switch.commands.switch._refresh_oauth_token", return_value="refreshed_tok"
        ):
            _apply_account_env(acc)
        assert os.environ["KAGGLE_API_TOKEN"] == "refreshed_tok"

    def test_oauth_no_token_no_creds(self, monkeypatch):
        """OAuth but no token and no credentials file — should not crash."""
        acc = Account(number="1", name="myoauth", config_dir="myoauth", auth_type="oauth")
        with patch(
            "kaggle_switch.commands.switch.get_token", return_value=""
        ), patch(
            "kaggle_switch.commands.switch._refresh_oauth_token", return_value=None
        ):
            _apply_account_env(acc)
        assert "KAGGLE_API_TOKEN" not in os.environ

    def test_oauth_copies_credentials_json(self, tmp_path, monkeypatch):
        """Lines 63-68: OAuth account copies credentials.json to ~/.kaggle/."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="1", name="myoauth", config_dir="myoauth", auth_type="oauth")

        oauth_dir = tmp_path / ".kaggle-myoauth"
        oauth_dir.mkdir(parents=True)
        (oauth_dir / "credentials.json").write_text('{"refresh_token": "rt1"}')

        with patch("kaggle_switch.commands.switch.get_token", return_value=""), \
             patch("kaggle_switch.commands.switch._refresh_oauth_token", return_value=None):
            _apply_account_env(acc)

        dest = tmp_path / ".kaggle" / "credentials.json"
        assert dest.exists()
        assert "rt1" in dest.read_text()

    def test_oauth_to_legacy_cleans_credentials_json(self, tmp_path, monkeypatch):
        """Line 70-71: legacy (non-oauth) account removes stale credentials.json."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        # Pre-create a stale credentials.json in ~/.kaggle/
        creds_dst = tmp_path / ".kaggle" / "credentials.json"
        creds_dst.parent.mkdir(parents=True)
        creds_dst.write_text("stale")

        acc = Account(number="2", name="legacy", config_dir="legacy", auth_type="")
        with patch("kaggle_switch.commands.switch.get_token", return_value=""):
            _apply_account_env(acc)

        assert not creds_dst.exists()

    def test_removes_credentials_json_for_default_legacy(self, tmp_path, monkeypatch):
        """Line 70-71: default account (empty config_dir) also cleans up."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        creds_dst = tmp_path / ".kaggle" / "credentials.json"
        creds_dst.parent.mkdir(parents=True)
        creds_dst.write_text("stale")

        acc = Account(number="1", name="default", config_dir="", auth_type="")
        with patch("kaggle_switch.commands.switch.get_token", return_value=""):
            _apply_account_env(acc)

        assert not creds_dst.exists()


# ── _wrapper_console ────────────────────────────────────────────


class TestWrapperConsole:
    def test_returns_stderr_console(self, monkeypatch):
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")
        con = _wrapper_console()
        assert con.file is sys.stderr

    def test_returns_default_console(self, monkeypatch):
        monkeypatch.delenv("KAGITCH_SHELL_WRAPPER", raising=False)
        from kaggle_switch.style import console as default_console

        con = _wrapper_console()
        assert con is default_console


# ── cmd_switch ──────────────────────────────────────────────────


class TestCmdSwitch:
    def test_account_not_found_has_accounts(self, tmp_path, monkeypatch):
        """Lines 87-89: account not found but others exist."""
        monkeypatch.setattr(
            "kaggle_switch.commands.switch.Path",
            MagicMock(home=classmethod(lambda cls: tmp_path)),
        )
        config = {
            "accounts": {
                "1": {"name": "alpha", "config_dir": "", "auth_type": ""},
                "2": {"name": "beta", "config_dir": "beta", "auth_type": ""},
            }
        }
        with patch("kaggle_switch.commands.switch._wrapper_console") as mock_wc:
            mock_con = MagicMock()
            mock_wc.return_value = mock_con
            rc = cmd_switch(config, "nonexistent")
        assert rc == 1
        from kaggle_switch.style import err as _err
        mock_con.print.assert_any_call(
            _err("Account 'nonexistent' not found")
        )

    def test_account_not_found_no_accounts_configured(self, tmp_path, monkeypatch):
        """Line 91: error message when no accounts at all."""
        monkeypatch.setattr(
            "kaggle_switch.commands.switch.Path",
            MagicMock(home=classmethod(lambda cls: tmp_path)),
        )
        config = {"accounts": {}}
        with patch("kaggle_switch.commands.switch._wrapper_console") as mock_wc:
            mock_con = MagicMock()
            mock_wc.return_value = mock_con
            rc = cmd_switch(config, "nonexistent")
        assert rc == 1
        from kaggle_switch.style import err as _err
        mock_con.print.assert_any_call(
            _err("No accounts configured \u2014 use [bold]kagitch add <name>[/]")
        )

    def test_account_found_with_username_and_patch(self, tmp_path, monkeypatch):
        """Lines 117-133: username display, _auto_patch_metadata, patch_line."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        config = {
            "accounts": {
                "1": {"name": "testacc", "config_dir": "testacc", "auth_type": "oauth"},
            }
        }
        save_config(config)

        acc_dir = tmp_path / ".kaggle-testacc"
        acc_dir.mkdir(parents=True)
        (acc_dir / "credentials.json").write_text('{"username": "testuser"}')

        with patch(
            "kaggle_switch.commands.kernel._auto_patch_metadata", return_value="  [dim]patched[/]"
        ) as mock_patch:
            rc = cmd_switch(load_config(), "1")

        assert rc == 0
        mock_patch.assert_called_once()

    def test_account_found_no_username(self, tmp_path, monkeypatch):
        """Line 130: path-only display when username is None."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        config = {
            "accounts": {
                "1": {"name": "testacc", "config_dir": "testacc", "auth_type": "oauth"},
            }
        }
        config_path = tmp_path / ".config" / "kagitch" / "accounts.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        acc_dir = tmp_path / ".kaggle-testacc"
        acc_dir.mkdir(parents=True)

        with patch(
            "kaggle_switch.commands.switch._active_username_from_account",
            return_value=None,
        ), patch("kaggle_switch.commands.switch.os.environ.get", return_value=""):
            rc = cmd_switch(load_config(), "1")

        assert rc == 0

    def test_shell_wrapper_mode_emits_token(self, tmp_path, monkeypatch):
        """Lines 104-105, 109-111: wrapper mode prints env lines with token."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        config = {
            "accounts": {
                "1": {"name": "testacc", "config_dir": "testacc", "auth_type": "oauth"},
            }
        }
        config_path = tmp_path / ".config" / "kagitch" / "accounts.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        acc_dir = tmp_path / ".kaggle-testacc"
        acc_dir.mkdir(parents=True)

        with patch(
            "kaggle_switch.commands.switch.get_token", return_value="mytoken"
        ), patch(
            "kaggle_switch.commands.switch._active_username_from_account",
            return_value=None,
        ):
            rc = cmd_switch(load_config(), "1")

        assert rc == 0

    def test_wrapper_mode_default_account_unset_config_dir(self, tmp_path, monkeypatch):
        """Line 98: default account emits 'unset KAGGLE_CONFIG_DIR' in wrapper."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        config = {
            "accounts": {
                "1": {"name": "default", "config_dir": "", "auth_type": ""},
            }
        }
        import kaggle_switch.config as cfg

        config_path = tmp_path / ".config" / "kagitch" / "accounts.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        with patch.object(cfg, "CONFIG_FILE", config_path), patch(
            "kaggle_switch.commands.switch.get_token", return_value=""
        ), patch(
            "kaggle_switch.commands.switch._active_username_from_account",
            return_value=None,
        ):
            rc = cmd_switch(load_config(), "1")

        assert rc == 0


# ── cmd_switch_prompt ───────────────────────────────────────────


class TestCmdSwitchPrompt:
    def test_no_accounts(self, tmp_path, monkeypatch):
        """Lines 146-147: no accounts configured."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config = {"accounts": {}}
        with patch("kaggle_switch.commands.switch._wrapper_console") as mock_wc:
            mock_con = MagicMock()
            mock_wc.return_value = mock_con
            rc = cmd_switch_prompt(config)
        assert rc == 1
        mock_con.print.assert_called_once()

    def test_wrapper_mode_accepts_choice(self, tmp_path, monkeypatch):
        """Lines 158-169: wrapper mode reads choice from input()."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        config = {
            "accounts": {
                "1": {"name": "alpha", "config_dir": ""},
                "2": {"name": "beta", "config_dir": "beta"},
            }
        }

        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("2\n"))

        with patch(
            "kaggle_switch.commands.switch.cmd_switch", return_value=0
        ) as mock_cmd:
            rc = cmd_switch_prompt(config)

        assert rc == 0
        mock_cmd.assert_called_once_with(config, "2")

    def test_wrapper_mode_eof(self, tmp_path, monkeypatch):
        """Lines 163-168: EOFError in wrapper mode returns 1 + prints Cancelled."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        config = {
            "accounts": {
                "1": {"name": "alpha", "config_dir": ""},
            }
        }

        with patch(
            "kaggle_switch.commands.switch.cmd_switch", return_value=0
        ), patch(
            "kaggle_switch.commands.switch.input", side_effect=EOFError
        ):
            rc = cmd_switch_prompt(config)

        assert rc == 1

    def test_wrapper_mode_keyboard_interrupt(self, tmp_path, monkeypatch):
        """Lines 163-168: KeyboardInterrupt in wrapper mode returns 1."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        config = {
            "accounts": {
                "1": {"name": "alpha", "config_dir": ""},
            }
        }

        with patch(
            "kaggle_switch.commands.switch.cmd_switch", return_value=0
        ), patch(
            "kaggle_switch.commands.switch.input", side_effect=KeyboardInterrupt
        ):
            rc = cmd_switch_prompt(config)

        assert rc == 1

    def test_interactive_mode_cancelled(self, tmp_path, monkeypatch):
        """Lines 174-177: Ctrl+C in interactive Prompt.ask returns 1."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        config = {
            "accounts": {
                "1": {"name": "alpha", "config_dir": ""},
            }
        }

        with patch(
            "kaggle_switch.commands.switch.Prompt.ask",
            side_effect=KeyboardInterrupt,
        ):
            rc = cmd_switch_prompt(config)

        assert rc == 1

    def test_interactive_mode_eof(self, tmp_path, monkeypatch):
        """Lines 174-177: EOFError in Prompt.ask returns 1."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        config = {
            "accounts": {
                "1": {"name": "alpha", "config_dir": ""},
            }
        }

        with patch(
            "kaggle_switch.commands.switch.Prompt.ask",
            side_effect=EOFError,
        ):
            rc = cmd_switch_prompt(config)

        assert rc == 1

    def test_wrapper_mode_invalid_choice(self, tmp_path, monkeypatch):
        """Lines 181-186: wrapper mode with invalid account choice."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        config = {
            "accounts": {
                "1": {"name": "alpha", "config_dir": ""},
            }
        }

        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("99\n"))

        with patch("kaggle_switch.commands.switch._wrapper_console") as mock_wc:
            mock_con = MagicMock()
            mock_wc.return_value = mock_con
            rc = cmd_switch_prompt(config)

        assert rc == 1
        assert any(
            "Invalid account" in str(call)
            for call in mock_con.print.call_args_list
        )


# ── _active_username_from_account ───────────────────────────────


class TestActiveUsernameFromAccount:
    def test_username_from_credentials_json(self, tmp_path, monkeypatch):
        """Happy path: reads username from credentials.json."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="1", name="test", config_dir="test")

        acc_dir = tmp_path / ".kaggle-test"
        acc_dir.mkdir(parents=True)
        (acc_dir / "credentials.json").write_text('{"username": "testuser", "refresh_token": "rt"}')

        result = _active_username_from_account(acc)
        assert result == "testuser"

    def test_username_from_kaggle_json(self, tmp_path, monkeypatch):
        """Fallback: reads username from kaggle.json."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="1", name="test", config_dir="test")

        acc_dir = tmp_path / ".kaggle-test"
        acc_dir.mkdir(parents=True)
        (acc_dir / "kaggle.json").write_text('{"username": "kguser", "key": "abc"}')

        result = _active_username_from_account(acc)
        assert result == "kguser"

    def test_credentials_json_malformed(self, tmp_path, monkeypatch):
        """Lines 201-203: JSONDecodeError in credentials.json — falls through."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="1", name="test", config_dir="test")

        acc_dir = tmp_path / ".kaggle-test"
        acc_dir.mkdir(parents=True)
        (acc_dir / "credentials.json").write_text("{invalid json")

        # No kaggle.json either
        result = _active_username_from_account(acc)
        assert result is None

    def test_kaggle_json_malformed(self, tmp_path, monkeypatch):
        """Lines 210-211: JSONDecodeError in kaggle.json — returns None."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="1", name="test", config_dir="test")

        acc_dir = tmp_path / ".kaggle-test"
        acc_dir.mkdir(parents=True)
        # Valid credentials.json but username missing
        (acc_dir / "credentials.json").write_text('{"refresh_token": "rt"}')
        # Malformed kaggle.json
        (acc_dir / "kaggle.json").write_text("{invalid")

        result = _active_username_from_account(acc)
        assert result is None

    def test_credentials_json_oserror(self, tmp_path, monkeypatch):
        """Lines 201-203: OSError reading credentials.json — falls through."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="1", name="test", config_dir="test")

        acc_dir = tmp_path / ".kaggle-test"
        acc_dir.mkdir(parents=True)

        # Create credentials.json but patch read_text to raise OSError
        creds_file = acc_dir / "credentials.json"
        creds_file.write_text('{"username": "testuser"}')

        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            result = _active_username_from_account(acc)

        # Falls through to kaggle.json, which doesn't exist
        assert result is None

    def test_credentials_json_username_missing(self, tmp_path, monkeypatch):
        """credentials.json exists but no username key — falls through to kaggle.json."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="1", name="test", config_dir="test")

        acc_dir = tmp_path / ".kaggle-test"
        acc_dir.mkdir(parents=True)
        (acc_dir / "credentials.json").write_text('{"refresh_token": "rt"}')
        (acc_dir / "kaggle.json").write_text('{"username": "kguser", "key": "abc"}')

        result = _active_username_from_account(acc)
        assert result == "kguser"

    def test_no_creds_at_all(self, tmp_path, monkeypatch):
        """Line 213: no credentials files — returns None."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="1", name="test", config_dir="test")

        acc_dir = tmp_path / ".kaggle-test"
        acc_dir.mkdir(parents=True)

        result = _active_username_from_account(acc)
        assert result is None


# ── Coverage for line 105 (export token in cmd_switch wrapper mode) ──


class TestCmdSwitchTokenExport:
    def test_wrapper_mode_emits_token_env(self, tmp_path, monkeypatch):
        """Line 104-105: wrapper mode prints export KAGGLE_API_TOKEN."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("KAGITCH_SHELL_WRAPPER", "1")

        config = {
            "accounts": {
                "1": {"name": "legacy", "config_dir": "", "auth_type": ""},
            }
        }
        config_path = tmp_path / ".config" / "kagitch" / "accounts.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        with patch(
            "kaggle_switch.commands.switch.get_token", return_value="tok_val"
        ), patch(
            "kaggle_switch.commands.switch._active_username_from_account",
            return_value=None,
        ), patch(
            "kaggle_switch.commands.kernel._auto_patch_metadata",
            return_value=None,
        ):
            rc = cmd_switch(load_config(), "1")

        assert rc == 0
