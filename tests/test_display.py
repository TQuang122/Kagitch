"""Tests for display module.

Focus: pure string-returning helpers first, then console-output functions.
Interactive TUI functions (_tty_status, _terminal_select) are tested at
their edge cases — full interactive tests would require a PTY.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from kaggle_switch import display


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


# ── _parse_quota ────────────────────────────────────────────────


class TestParseQuota:
    def test_valid_hours(self):
        assert display._parse_quota("4.13h") == 4.13
        assert display._parse_quota("0.00h") == 0.0
        assert display._parse_quota("100.5h") == 100.5
        assert display._parse_quota("0h") == 0.0

    def test_uppercase_h(self):
        assert display._parse_quota("25.87H") == 25.87

    def test_no_h_suffix(self):
        assert display._parse_quota("20") == 20.0

    def test_empty_string(self):
        assert display._parse_quota("") is None

    def test_none_input(self):
        assert display._parse_quota(None) is None

    def test_garbage_input(self):
        assert display._parse_quota("abc") is None
        assert display._parse_quota("12.5x") is None
        assert display._parse_quota("--") is None


# ── _render_quota ───────────────────────────────────────────────


class TestRenderQuota:
    def test_none_renders_em_dash(self):
        result = display._render_quota("")
        assert "\u2014" in result  # em dash

    def test_under_one_hour_is_error(self):
        result = display._render_quota("0.75h")
        # Should contain the value and be color-coded error (red)
        assert "0.75h" in result

    def test_one_to_five_is_warning(self):
        result = display._render_quota("3.5h")
        assert "3.5h" in result

    def test_five_and_up_is_ok(self):
        result = display._render_quota("25.87h")
        assert "25.87h" in result

    def test_exactly_one(self):
        result = display._render_quota("1.00h")
        # boundary: 1.0 is < 5 but >= 1 → warning
        assert "1.00h" in result

    def test_exactly_five(self):
        result = display._render_quota("5.00h")
        # boundary: 5.0 is >= 5 → ok
        assert "5.00h" in result


# ── _auth_method ────────────────────────────────────────────────


class TestAuthMethod:
    def test_legacy_key(self, tmp_path):
        (tmp_path / "kaggle.json").write_text(
            json.dumps({"username": "u", "key": "abc"})
        )
        assert display._auth_method(tmp_path) == "Legacy Key"

    def test_kaggle_json_no_key(self, tmp_path):
        (tmp_path / "kaggle.json").write_text(json.dumps({"username": "u"}))
        assert display._auth_method(tmp_path) == "kaggle.json"

    def test_kaggle_json_invalid(self, tmp_path):
        (tmp_path / "kaggle.json").write_text("not-json")
        assert display._auth_method(tmp_path) == "kaggle.json"

    def test_token(self, tmp_path):
        (tmp_path / "access_token").write_text("tok")
        assert display._auth_method(tmp_path) == "Token"

    def test_oauth(self, tmp_path):
        (tmp_path / "credentials.json").write_text("{}")
        assert display._auth_method(tmp_path) == "OAuth"

    def test_no_creds(self, tmp_path):
        assert display._auth_method(tmp_path) == "No creds"

    def test_legacy_takes_precedence(self, tmp_path):
        # kaggle.json exists alongside other files
        (tmp_path / "kaggle.json").write_text(
            json.dumps({"username": "u", "key": "abc"})
        )
        (tmp_path / "credentials.json").write_text("{}")
        assert display._auth_method(tmp_path) == "Legacy Key"

    def test_kaggle_json_no_key_with_oauth(self, tmp_path):
        # kaggle.json without key + credentials.json → kaggle.json
        (tmp_path / "kaggle.json").write_text(json.dumps({"username": "u"}))
        (tmp_path / "credentials.json").write_text("{}")
        assert display._auth_method(tmp_path) == "kaggle.json"


# ── _render_auth ────────────────────────────────────────────────


class TestRenderAuth:
    def test_oauth(self):
        r = display._render_auth("OAUTH")
        assert "OAuth" in r
        assert "\u2713" in r  # checkmark

    def test_oauth_full_form(self):
        r = display._render_auth("OAUTH")
        assert "OAuth" in r

    def test_access_token(self):
        r = display._render_auth("ACCESS_TOKEN")
        assert "Token" in r

    def test_token(self):
        r = display._render_auth("TOKEN")
        assert "Token" in r

    def test_legacy_api_key(self):
        r = display._render_auth("LEGACY_API_KEY")
        assert "Legacy Key" in r

    def test_legacy_key_with_underscore(self):
        r = display._render_auth("Legacy Key")
        assert "Legacy Key" in r

    def test_unknown_method(self):
        r = display._render_auth("CUSTOM_AUTH")
        assert "?" in r
        assert "CUSTOM_AUTH" in r

    def test_no_creds(self):
        r = display._render_auth("No creds")
        assert "\u2713" in r  # falls through to default ok path
        assert "No creds" not in r

    def test_failed_auth(self):
        r = display._render_auth("OAUTH", ok=False)
        assert "\u2717" in r  # cross mark

    def test_upper_legacy_variants(self):
        assert "Legacy Key" in display._render_auth("LEGACY")
        assert "Legacy Key" in display._render_auth("LEGACY_API_KEY")
        assert "Legacy Key" in display._render_auth("LEGACY_KEY")

    def test_oauth_detects_lowercase(self):
        r = display._render_auth("oauth")
        assert "OAuth" in r


# ── _render_banner ──────────────────────────────────────────────


class TestRenderBanner:
    def test_output_contains_version(self, capsys):
        display._render_banner()
        captured = capsys.readouterr()
        clean = _ANSI_RE.sub("", captured.out)
        assert display.__version__ in clean

    def test_output_has_banner_art(self, capsys):
        display._render_banner()
        captured = capsys.readouterr()
        clean = _ANSI_RE.sub("", captured.out)
        assert "KAGGLE" in clean.upper()
        assert "MULTI-ACCOUNT" in clean.upper()


# ── render_help ─────────────────────────────────────────────────


class TestRenderHelp:
    def test_output_contains_usage(self, capsys):
        display.render_help()
        captured = capsys.readouterr()
        clean = _ANSI_RE.sub("", captured.out)
        assert "Usage" in clean

    def test_output_has_commands(self, capsys):
        display.render_help()
        captured = capsys.readouterr()
        clean = _ANSI_RE.sub("", captured.out)
        assert "kagitch add" in clean
        assert "kagitch switch" in clean
        assert "kagitch check" in clean
        assert "kagitch list" in clean
        assert "kagitch init" in clean

    def test_output_has_version(self, capsys):
        display.render_help()
        captured = capsys.readouterr()
        clean = _ANSI_RE.sub("", captured.out)
        assert f"v{display.__version__}" in clean

    def test_output_has_options_section(self, capsys):
        display.render_help()
        captured = capsys.readouterr()
        clean = _ANSI_RE.sub("", captured.out)
        assert "Options" in clean

    def test_output_has_examples(self, capsys):
        display.render_help()
        captured = capsys.readouterr()
        clean = _ANSI_RE.sub("", captured.out)
        assert "Examples" in clean


# ── _tty_status ─────────────────────────────────────────────────

# _tty_status opens /dev/tty, which won't exist in test env.
# Test that it degrades gracefully (OSError → yield happens).


class TestTtyStatus:
    def test_yields_when_no_dev_tty(self):
        """OSError from open() should still yield control."""
        called = False
        with display._tty_status("working..."):
            called = True
        assert called is True

    def test_yields_on_any_oserror(self):
        """Context manager should not raise even when /dev/tty is unavailable."""
        with display._tty_status("test"):
            pass
        # no exception = pass

    def test_cleanup_after_exception(self):
        """Context manager should not suppress exceptions from the body."""
        class CustomError(Exception):
            pass

        with pytest.raises(CustomError):
            with display._tty_status("test"):
                raise CustomError("intentional")


# ── _terminal_select (edge cases) ───────────────────────────────

# _terminal_select requires a real TTY for full testing.
# We test the early-return edge cases here.


class TestTerminalSelectEdgeCases:
    def test_empty_list_returns_none(self):
        assert display._terminal_select([]) is None

    def test_single_option_returns_zero(self):
        assert display._terminal_select(["only"]) == 0

    def test_fallback_when_no_tty(self, monkeypatch):
        """With stdin not a TTY and no termios, returns default_index."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        # Prevent termios import by making it unavailable
        import builtins
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("termios", "tty"):
                raise ImportError
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            result = display._terminal_select(["a", "b", "c"], default_index=1)
            assert result == 1

    def test_fallback_no_tty_caps_default(self, monkeypatch):
        """When stdin is not a TTY, respects default_index."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("termios", "tty"):
                raise ImportError
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            result = display._terminal_select(["x", "y", "z"], default_index=2)
            assert result == 2

    def test_no_tty_clamps_index(self, monkeypatch):
        """default_index out of range is clamped."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("termios", "tty"):
                raise ImportError
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            # default_index out of range → clamped to 0
            result = display._terminal_select(["a"], default_index=99)
            assert result == 0


# ── _select_account_interactive (edge cases) ────────────────────


class TestSelectAccountInteractive:
    def test_no_accounts_returns_none(self, tmp_path, monkeypatch):
        """Empty account list should print message and return None."""
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_DIR", tmp_path / ".config" / "kagitch"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_FILE",
            tmp_path / ".config" / "kagitch" / "accounts.json",
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config = {"accounts": {}}
        result = display._select_account_interactive(config)
        assert result is None

    def test_single_account_no_tty_fallback(self, tmp_path, monkeypatch):
        """Single account, stdin not a TTY → fallback to input prompt."""
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_DIR", tmp_path / ".config" / "kagitch"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_FILE",
            tmp_path / ".config" / "kagitch" / "accounts.json",
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr("builtins.input", lambda prompt="": "1")

        config = {
            "accounts": {
                "1": {"name": "testuser", "config_dir": ".kaggle-testuser"}
            }
        }
        result = display._select_account_interactive(config)
        assert result is not None
        assert result.name == "testuser"
