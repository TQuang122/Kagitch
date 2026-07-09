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
from unittest.mock import MagicMock, patch

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


class TestFitPlain:
    def test_returns_plain_when_width_sufficient(self):
        assert display._fit_plain("abc", 3) == "abc"

    def test_truncates_with_ellipsis(self):
        assert display._fit_plain("abcdef", 4) == "abc…"

    def test_width_one(self):
        assert display._fit_plain("abcdef", 1) == "a"


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

    def test_success_path_opens_and_closes_tty(self):
        """When /dev/tty opens, close it and yield control."""
        mock_file = MagicMock()
        mock_console = MagicMock()
        with patch("builtins.open", return_value=mock_file):
            with patch("kaggle_switch.display.Console", return_value=mock_console):
                called = False
                with display._tty_status("working..."):
                    called = True
                assert called is True
        mock_file.close.assert_called_once()


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


# ── _terminal_select (interactive flow) ─────────────────────────


class TestTerminalSelectInteractive:

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _setup_stdin(monkeypatch, key_sequence):
        import termios
        import tty

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 999)

        old_attrs = b"old"
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: old_attrs)
        monkeypatch.setattr(
            termios, "tcsetattr", lambda fd, act, attrs: None
        )
        monkeypatch.setattr(tty, "setraw", lambda fd: None)

        it = iter(key_sequence)
        monkeypatch.setattr(sys.stdin, "read", lambda n: next(it))
        return it

    # ── positive selection ───────────────────────────────────────

    def test_enter_selects_default(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\r"])
        assert display._terminal_select(["A", "B", "C"], 0) == 0

    def test_enter_newline_selects_default(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\n"])
        assert display._terminal_select(["A", "B", "C"], 1) == 1

    def test_arrow_down_selects_next(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\x1b", "[B", "\r"])
        assert display._terminal_select(["A", "B", "C"]) == 1

    def test_arrow_down_repeated(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\x1b", "[B", "\x1b", "[B", "\r"])
        assert display._terminal_select(["A", "B", "C"]) == 2

    def test_arrow_up_selects_previous(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\x1b", "[A", "\x1b", "[A", "\r"])
        assert display._terminal_select(["A", "B", "C"], 2) == 0

    def test_arrow_up_wraps_to_last(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\x1b", "[A", "\r"])
        assert display._terminal_select(["A", "B", "C"], 0) == 2

    def test_arrow_down_wraps_to_first(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\x1b", "[B", "\r"])
        assert display._terminal_select(["A", "B", "C"], 2) == 0

    def test_mixed_arrows(self, monkeypatch):
        self._setup_stdin(
            monkeypatch, ["\x1b", "[B", "\x1b", "[B", "\x1b", "[A", "\r"]
        )
        assert display._terminal_select(["A", "B", "C"], 0) == 1

    # ── cancellation ─────────────────────────────────────────────

    def test_q_cancels(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["q"])
        assert display._terminal_select(["A", "B"]) is None

    def test_ctrl_c_returns_none(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\x03"])
        assert display._terminal_select(["A", "B"]) is None

    def test_eof_error_returns_none(self, monkeypatch):
        import termios
        import tty

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 999)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: b"old")
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, a, a2: None)
        monkeypatch.setattr(tty, "setraw", lambda fd: None)
        monkeypatch.setattr(
            sys.stdin,
            "read",
            lambda n: (_ for _ in ()).throw(EOFError()),
        )
        assert display._terminal_select(["A", "B"]) is None

    # ── ignored input ────────────────────────────────────────────

    def test_non_special_chars_ignored(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["x", " ", "\r"])
        assert display._terminal_select(["A", "B", "C"]) == 0

    def test_unknown_escape_ignored(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\x1b", "[C", "\r"])
        assert display._terminal_select(["A", "B", "C"]) == 0

    def test_escape_without_full_sequence_ignored(self, monkeypatch):
        self._setup_stdin(monkeypatch, ["\x1b", "\r", "\r"])
        # read(2) consumes '\r' and continues since rest != '[A' or '[B';
        # second '\r' breaks the loop
        assert display._terminal_select(["A", "B", "C"]) == 0

    # ── /dev/tty path ────────────────────────────────────────────

    def test_dev_tty_used_when_stderr_not_tty(self, monkeypatch):
        import termios
        import tty

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 999)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: b"old")
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, a, a2: None)
        monkeypatch.setattr(tty, "setraw", lambda fd: None)

        it = iter(["\r"])
        monkeypatch.setattr(sys.stdin, "read", lambda n: next(it))

        mock_file = MagicMock()
        with patch("builtins.open", return_value=mock_file) as mock_open:
            result = display._terminal_select(["A", "B"])

        assert result == 0
        mock_open.assert_called_once_with("/dev/tty", "w")
        mock_file.close.assert_called_once()

    def test_rich_card_layout_contains_title_footer_and_border(self, monkeypatch):
        import termios
        import tty

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 999)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: b"old")
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, a, a2: None)
        monkeypatch.setattr(tty, "setraw", lambda fd: None)

        it = iter(["\r"])
        monkeypatch.setattr(sys.stdin, "read", lambda n: next(it))

        mock_file = MagicMock()
        with patch("builtins.open", return_value=mock_file):
            result = display._terminal_select(
                ["1. alpha", "2. beta"],
                default_index=1,
                title="Choose account for kernel logs",
                footer="↑/↓ move • Enter select • q cancel",
                subtexts=["available account", "current default account"],
                active_index=1,
            )

        assert result == 1
        written = "".join(call.args[0] for call in mock_file.write.call_args_list)
        assert "Choose account for kernel logs" in written
        assert "ACTIVE" in written
        assert "current default account" in written
        assert "Enter select" in written
        assert "┌" in written and "└" in written

        clean = _ANSI_RE.sub("", written)
        lines = [line for line in clean.splitlines() if line]
        selected_lines = [line for line in lines if line.startswith("┌") or line.startswith("│") or line.startswith("└")]
        widths = {len(line) for line in selected_lines}
        assert len(widths) == 1

    def test_rich_card_layout_strips_ansi_status_and_keeps_alignment(self, monkeypatch):
        import termios
        import tty

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 999)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: b"old")
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, a, a2: None)
        monkeypatch.setattr(tty, "setraw", lambda fd: None)

        it = iter(["\r"])
        monkeypatch.setattr(sys.stdin, "read", lambda n: next(it))

        mock_file = MagicMock()
        with patch("builtins.open", return_value=mock_file):
            result = display._terminal_select(
                [
                    "1. thanhquang71/kernel-flyp-reproduce  \x1b[32m(COMPLETE)\x1b[0m",
                    "2. another-kernel  \x1b[1;31m(ERROR)\x1b[0m",
                ],
                default_index=0,
                title="Choose kernel",
                footer="↑/↓ move • Enter select • q cancel",
            )

        assert result == 0
        written = "".join(call.args[0] for call in mock_file.write.call_args_list)
        clean = _ANSI_RE.sub("", written)
        lines = [line for line in clean.splitlines() if line]
        selected_lines = [line for line in lines if line.startswith("┌") or line.startswith("│") or line.startswith("└")]
        widths = {len(line) for line in selected_lines}
        assert len(widths) == 1
        assert "(COMPLETE)" in clean

    def test_dev_tty_oserror_falls_back_to_stderr(self, monkeypatch):
        import termios
        import tty

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 999)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: b"old")
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, a, a2: None)
        monkeypatch.setattr(tty, "setraw", lambda fd: None)

        it = iter(["\r"])
        monkeypatch.setattr(sys.stdin, "read", lambda n: next(it))

        with patch("builtins.open", side_effect=OSError("no tty")):
            result = display._terminal_select(["A", "B"])

        assert result == 0

    def test_dev_tty_fallback_when_no_termios(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

        mock_file = MagicMock()
        with patch("builtins.open", return_value=mock_file):
            with patch.dict(
                "sys.modules", {"termios": None, "tty": None}, clear=False
            ):
                result = display._terminal_select(["A", "B", "C"], 2)

        assert result == 2
        mock_file.close.assert_called_once()

    def test_stdin_not_tty_after_termios_import(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
        result = display._terminal_select(["A", "B", "C"], 1)
        assert result == 1

    def test_stdin_not_tty_with_dev_tty_opened(self, monkeypatch):
        """stdin not TTY but /dev/tty was opened → tty_out.close() called."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
        mock_file = MagicMock()
        with patch("builtins.open", return_value=mock_file):
            result = display._terminal_select(["A", "B", "C"], 1)
        assert result == 1
        mock_file.close.assert_called_once()

    def test_stdin_not_tty_with_dev_tty_oserror(self, monkeypatch):
        """stdin not TTY, /dev/tty open fails → no close call, returns default."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
        with patch("builtins.open", side_effect=OSError("no tty")):
            result = display._terminal_select(["A", "B", "C"], 2)
        assert result == 2


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

    def test_two_accounts_tty_branch(self, tmp_path, monkeypatch):
        """Two accounts, stdin is TTY → uses _terminal_select for interactive pick."""
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_DIR", tmp_path / ".config" / "kagitch"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_FILE",
            tmp_path / ".config" / "kagitch" / "accounts.json",
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        config = {
            "accounts": {
                "1": {"name": "alice", "config_dir": ".kaggle-alice"},
                "2": {"name": "bob", "config_dir": ".kaggle-bob"},
            }
        }
        with patch("kaggle_switch.display._terminal_select", return_value=1) as mock_select:
            result = display._select_account_interactive(config)

        assert result is not None
        assert result.name == "bob"
        kwargs = mock_select.call_args.kwargs
        assert kwargs["title"] == "Choose account for kernel logs"
        assert "Enter select" in kwargs["footer"]
        assert kwargs["active_index"] == 0

    def test_tty_branch_cancelled(self, tmp_path, monkeypatch):
        """TTY branch where user cancels → returns None."""
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_DIR", tmp_path / ".config" / "kagitch"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_FILE",
            tmp_path / ".config" / "kagitch" / "accounts.json",
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        config = {
            "accounts": {
                "1": {"name": "alice", "config_dir": ".kaggle-alice"},
            }
        }
        with patch("kaggle_switch.display._terminal_select", return_value=None):
            result = display._select_account_interactive(config)

        assert result is None

    def test_fallback_input_eof(self, tmp_path, monkeypatch):
        """Fallback prompt raises EOFError → returns None."""
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_DIR", tmp_path / ".config" / "kagitch"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_FILE",
            tmp_path / ".config" / "kagitch" / "accounts.json",
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr("builtins.input", MagicMock(side_effect=EOFError()))

        config = {
            "accounts": {
                "1": {"name": "testuser", "config_dir": ".kaggle-testuser"},
            }
        }
        result = display._select_account_interactive(config)
        assert result is None

    def test_fallback_invalid_choice(self, tmp_path, monkeypatch):
        """Fallback prompt receives non-matching input → returns None."""
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_DIR", tmp_path / ".config" / "kagitch"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_FILE",
            tmp_path / ".config" / "kagitch" / "accounts.json",
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr("builtins.input", lambda prompt="": "999")

        config = {
            "accounts": {
                "1": {"name": "testuser", "config_dir": ".kaggle-testuser"},
            }
        }
        result = display._select_account_interactive(config)
        assert result is None

    def test_account_with_active(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_DIR", tmp_path / ".config" / "kagitch"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_FILE",
            tmp_path / ".config" / "kagitch" / "accounts.json",
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        acc2_path = tmp_path / ".kaggle-active2"
        acc2_path.mkdir(parents=True)
        monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(acc2_path))
        monkeypatch.setattr(
            "kaggle_switch.config.KAGGLE_DEFAULT", tmp_path / ".kaggle"
        )
        monkeypatch.setattr("builtins.input", lambda prompt="": "2")

        config = {
            "accounts": {
                "1": {"name": "first", "config_dir": "first"},
                "2": {"name": "active2", "config_dir": "active2"},
            }
        }
        result = display._select_account_interactive(config)
        assert result is not None
        assert result.name == "active2"


class TestFileContextManager:
    def test_close_raises_exception(self):
        mock_file = MagicMock()
        mock_file.close.side_effect = RuntimeError("close failed")
        with patch("builtins.open", return_value=mock_file):
            with patch("kaggle_switch.display.Console") as mock_console:
                mock_console.return_value.status.return_value.__enter__ = MagicMock()
                mock_console.return_value.status.return_value.__exit__ = MagicMock()
                with display._tty_status("testing"):
                    pass
