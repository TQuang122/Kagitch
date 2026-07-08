"""Tests for setup module (init, shellpath, completions, update)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from kaggle_switch.commands import setup as mod


# ── cmd_shellpath ────────────────────────────────────────────────


class TestCmdShellpath:
    def test_with_shell_arg(self, capsys):
        with patch.object(mod, "shellpath", return_value="the-path") as mock_sp:
            rc = mod.cmd_shellpath(["fish"])
        assert rc == 0
        mock_sp.assert_called_once_with("fish")
        captured = capsys.readouterr()
        assert captured.out == "the-path"

    def test_no_args_detects_shell(self, capsys):
        with patch.object(mod, "shellpath", return_value="/bin/zsh") as mock_sp, \
             patch.object(mod, "detect_shell", return_value="zsh") as mock_ds:
            rc = mod.cmd_shellpath([])
        assert rc == 0
        mock_ds.assert_called_once()
        mock_sp.assert_called_once_with("zsh")
        captured = capsys.readouterr()
        assert captured.out == "/bin/zsh"

    def test_shellpath_raises_value_error(self):
        with patch.object(mod, "shellpath", side_effect=ValueError("bad shell")):
            rc = mod.cmd_shellpath(["tcsh"])
        assert rc == 1


# ── cmd_completions ──────────────────────────────────────────────


class TestCmdCompletions:
    def test_with_shell_arg(self, capsys):
        with patch.object(mod, "shell_completions", return_value="# COMPLETION\n") as mock_sc:
            rc = mod.cmd_completions(["zsh"])
        assert rc == 0
        mock_sc.assert_called_once_with("zsh")
        assert capsys.readouterr().out == "# COMPLETION\n"

    def test_no_args_detects_shell(self, capsys):
        with patch.object(mod, "shell_completions", return_value="comp") as mock_sc, \
             patch.object(mod, "detect_shell", return_value="bash") as mock_ds:
            rc = mod.cmd_completions([])
        assert rc == 0
        mock_ds.assert_called_once()
        mock_sc.assert_called_once_with("bash")

    def test_raises_value_error(self):
        with patch.object(mod, "shell_completions", side_effect=ValueError("bad")):
            rc = mod.cmd_completions(["tcsh"])
        assert rc == 1


# ── cmd_init ─────────────────────────────────────────────────────


class TestCmdInitReload:
    """kagitch init -r / --reload"""

    def test_reload_found(self):
        """--reload, rc exists, kagitch integration found -> calls _reload."""
        mock_rc = MagicMock(spec=Path)
        mock_rc.exists.return_value = True
        mock_rc.read_text.return_value = 'eval "$(kagitch init)" # kagitch shellpath'
        with patch.object(mod, "rc_file_for_shell", return_value=mock_rc) as mock_rcf, \
             patch.object(mod, "detect_shell", return_value="zsh") as mock_ds, \
             patch.object(mod, "_reload") as mock_rl:
            rc = mod.cmd_init(["-r"])
        assert rc == 0
        mock_ds.assert_called_once()
        mock_rcf.assert_called_once_with("zsh")
        mock_rl.assert_called_once_with("zsh")

    def test_reload_no_integration(self):
        """--reload, rc exists but no kagitch integration."""
        mock_rc = MagicMock(spec=Path)
        mock_rc.exists.return_value = True
        mock_rc.read_text.return_value = "# just some stuff"
        with patch.object(mod, "rc_file_for_shell", return_value=mock_rc), \
             patch.object(mod, "detect_shell", return_value="zsh"), \
             patch.object(mod, "_reload") as mock_rl:
            rc = mod.cmd_init(["-r"])
        assert rc == 1
        mock_rl.assert_not_called()

    def test_reload_rc_not_exists(self):
        """--reload, rc file does not exist."""
        mock_rc = MagicMock(spec=Path)
        mock_rc.exists.return_value = False
        with patch.object(mod, "rc_file_for_shell", return_value=mock_rc), \
             patch.object(mod, "detect_shell", return_value="zsh"), \
             patch.object(mod, "_reload") as mock_rl:
            rc = mod.cmd_init(["-r"])
        assert rc == 1
        mock_rl.assert_not_called()

    def test_reload_rc_none(self):
        """--reload, rc_file_for_shell returns None."""
        with patch.object(mod, "rc_file_for_shell", return_value=None), \
             patch.object(mod, "detect_shell", return_value="zsh"), \
             patch.object(mod, "_reload") as mock_rl:
            rc = mod.cmd_init(["-r"])
        assert rc == 1
        mock_rl.assert_not_called()

    def test_reload_alias_r(self):
        """Double-dash alias --reload works."""
        mock_rc = MagicMock(spec=Path)
        mock_rc.exists.return_value = True
        mock_rc.read_text.return_value = 'eval "$(kagitch shellpath)"'
        with patch.object(mod, "rc_file_for_shell", return_value=mock_rc), \
             patch.object(mod, "detect_shell", return_value="zsh"), \
             patch.object(mod, "_reload") as mock_rl:
            rc = mod.cmd_init(["--reload"])
        assert rc == 0
        mock_rl.assert_called_once_with("zsh")


class TestCmdInitNormal:
    """Normal init flow (no --reload, no shell wrapper)."""

    def test_runs_wizard(self):
        with patch("kaggle_switch.init_wizard.run_wizard", return_value=7) as mock_wiz:
            rc = mod.cmd_init()
        assert rc == 7
        mock_wiz.assert_called_once_with()

    def test_runs_wizard_with_extra_args_ignored(self):
        with patch("kaggle_switch.init_wizard.run_wizard", return_value=0) as mock_wiz:
            rc = mod.cmd_init(["some", "extra"])
        assert rc == 0
        mock_wiz.assert_called_once_with()


class TestCmdInitShellWrapper:
    """Init under KAGITCH_SHELL_WRAPPER env — opens /dev/tty."""

    def test_tty_success(self):
        mock_tty = MagicMock()
        with patch.dict("os.environ", {"KAGITCH_SHELL_WRAPPER": "1"}), \
             patch("builtins.open", return_value=mock_tty) as mock_open, \
             patch("kaggle_switch.init_wizard.run_wizard", return_value=3) as mock_wiz:
            rc = mod.cmd_init()
        assert rc == 3
        mock_open.assert_called_once_with("/dev/tty", "w")
        mock_tty.close.assert_called_once()
        mock_wiz.assert_called_once()
        assert mock_wiz.call_args.kwargs["con"] is not None

        flush_wrapper = mock_wiz.call_args.kwargs["con"].file
        flush_wrapper.write("hello")
        flush_wrapper.flush()
        mock_tty.write.assert_called_with("hello")
        assert mock_tty.flush.call_count >= 2

    def test_tty_oserror_fallback(self):
        """When /dev/tty open fails, fall through to normal wizard."""
        with patch.dict("os.environ", {"KAGITCH_SHELL_WRAPPER": "1"}), \
             patch("builtins.open", side_effect=OSError("no tty")), \
             patch("kaggle_switch.init_wizard.run_wizard", return_value=0) as mock_wiz:
            rc = mod.cmd_init()
        assert rc == 0
        mock_wiz.assert_called_once_with()


# ── _reload ──────────────────────────────────────────────────────


class TestReload:
    def test_powershell_with_profile(self):
        """powershell with existing profile shows panel."""
        mock_profile = MagicMock(spec=Path)
        mock_profile.__fspath__ = lambda self: "/ps/profile.ps1"
        with patch.object(mod, "rc_file_for_shell", return_value=mock_profile), \
             patch.object(mod, "console") as mock_con:
            mod._reload("powershell")
        mock_con.print.assert_called()
        panel_call = mock_con.print.call_args[0][0]
        assert hasattr(panel_call, "title")

    def test_powershell_no_profile(self):
        with patch.object(mod, "rc_file_for_shell", return_value=None), \
             patch.object(mod, "console") as mock_con:
            mod._reload("powershell")
        mock_con.print.assert_called_once()
        assert "Restart" in str(mock_con.print.call_args[0][0])

    def test_unix_rc_none(self):
        """detected shell but rc_file_for_shell returns None."""
        with patch.object(mod, "rc_file_for_shell", return_value=None), \
             patch.object(mod, "console") as mock_con, \
             patch.object(mod, "os") as mock_os:
            mod._reload("zsh")
        mock_con.print.assert_called_once()
        mock_os.execvp.assert_not_called()

    def test_shell_wrapper_mode(self):
        """_reload under KAGITCH_SHELL_WRAPPER redirects fds to /dev/tty."""
        mock_rc = MagicMock(spec=Path)
        mock_rc.__fspath__ = lambda self: "/home/user/.zshrc"
        mock_rc.exists.return_value = True
        with patch.dict("os.environ", {"KAGITCH_SHELL_WRAPPER": "1"}), \
             patch.object(mod, "rc_file_for_shell", return_value=mock_rc), \
             patch.object(mod, "console"), \
             patch("builtins.open"), \
             patch.object(mod, "os") as mock_os:
            mock_os.open.return_value = 3
            mock_os.fdopen.side_effect = lambda fd, mode: MagicMock()
            mod._reload("zsh")
        mock_os.open.assert_called_once_with("/dev/tty", mock_os.O_RDWR)
        mock_os.dup2.assert_has_calls([call(3, 1), call(3, 2)])
        mock_os.close.assert_called_once_with(3)
        mock_os.execvp.assert_called_once_with("zsh", ["zsh", "-l"])

    def test_shell_wrapper_tty_fail(self):
        """_reload under wrapper but /dev/tty open fails."""
        mock_rc = MagicMock(spec=Path)
        mock_rc.__fspath__ = lambda self: "/home/user/.zshrc"
        with patch.dict("os.environ", {"KAGITCH_SHELL_WRAPPER": "1"}), \
             patch.object(mod, "rc_file_for_shell", return_value=mock_rc), \
             patch.object(mod, "console"), \
             patch.object(mod, "os") as mock_os:
            mock_os.open.side_effect = OSError("no tty")
            mod._reload("zsh")
        mock_os.execvp.assert_called_once_with("zsh", ["zsh", "-l"])

    def test_normal_mode(self):
        """Normal mode (no wrapper) prints panel and exec's."""
        mock_rc = MagicMock(spec=Path)
        mock_rc.__fspath__ = lambda self: "/home/user/.zshrc"
        with patch.object(mod, "rc_file_for_shell", return_value=mock_rc), \
             patch.object(mod, "console") as mock_con, \
             patch("os.execvp") as mock_exec:
            mod._reload("zsh")
        mock_con.print.assert_called()
        mock_exec.assert_called_once_with("zsh", ["zsh", "-l"])


# ── _git_log / _git_head ────────────────────────────────────────


class TestGitLog:
    def test_returns_stdout_stripped(self):
        with patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc123\n"
            )
            result = mod._git_log("log", "-1", cwd=Path("/repo"))
        assert result == "abc123"
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["git", "log", "-1"]

    def test_empty_stdout(self):
        with patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=""
            )
            result = mod._git_log("log", "-1", "--oneline", cwd=Path("/repo"))
        assert result == ""


class TestGitHead:
    def test_normal(self):
        with patch.object(mod, "_git_log", return_value="abc123 fix stuff"):
            result = mod._git_head(Path("/repo"))
        assert result == ["abc123", "fix stuff"]

    def test_empty_output(self):
        with patch.object(mod, "_git_log", return_value=""):
            result = mod._git_head(Path("/repo"))
        assert result == ["?", "?"]

    def test_single_part_no_subject(self):
        with patch.object(mod, "_git_log", return_value="abc123"):
            result = mod._git_head(Path("/repo"))
        assert result == ["abc123", ""]


# ── cmd_update ───────────────────────────────────────────────────


class TestCmdUpdateNotGit:
    """cmd_update when .git dir does not exist."""

    def test_not_a_git_installation(self):
        with patch.object(Path, "is_dir", return_value=False), \
             patch.object(mod, "console") as mock_con:
            rc = mod.cmd_update()
        assert rc == 1
        mock_con.print.assert_called()


class TestCmdUpdatePullFailed:
    def test_git_pull_fails(self):
        mock_failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="merge conflict"
        )
        with patch.object(Path, "is_dir", return_value=True), \
             patch.object(mod, "_git_head", return_value=["abc", "old"]), \
             patch.object(mod.subprocess, "run", return_value=mock_failed), \
             patch.object(mod, "console") as mock_con:
            rc = mod.cmd_update()
        assert rc == 1
        mock_con.print.assert_called()


class TestCmdUpdateAlreadyUpToDate:
    def test_already_up_to_date(self):
        mock_uptodate = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Already up to date.\n", stderr=""
        )
        with patch.object(Path, "is_dir", return_value=True), \
             patch.object(mod, "_git_head", return_value=["abc", "old"]), \
             patch.object(mod.subprocess, "run", return_value=mock_uptodate), \
             patch.object(mod, "console") as mock_con:
            rc = mod.cmd_update()
        assert rc == 0
        mock_con.print.assert_called()


class TestCmdUpdateSuccess:
    def test_successful_update(self):
        mock_success = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Updating abc..def\n 1 file changed\n", stderr=""
        )
        with patch.object(Path, "is_dir", return_value=True), \
             patch.object(mod, "_git_head", side_effect=[["abc", "old"], ["def", "new stuff"]]), \
             patch.object(mod, "_git_log", return_value="def new stuff\n"), \
             patch.object(mod.subprocess, "run", return_value=mock_success), \
             patch.object(mod, "console") as mock_con:
            rc = mod.cmd_update()
        assert rc == 0
        mock_con.print.assert_called()

    def test_successful_update_one_commit(self):
        mock_success = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Updating abc..def\n 1 file changed\n", stderr=""
        )
        with patch.object(Path, "is_dir", return_value=True), \
             patch.object(mod, "_git_head", side_effect=[["abc", "old"], ["def", "new"]]), \
             patch.object(mod, "_git_log", return_value="def new\n"), \
             patch.object(mod.subprocess, "run", return_value=mock_success), \
             patch.object(mod, "console"):
            rc = mod.cmd_update()
        assert rc == 0


class TestCmdUpdateShellWrapper:
    def test_wrapper_mode(self):
        """Under KAGITCH_SHELL_WRAPPER, doesn't use console.status."""
        mock_success = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Already up to date.\n", stderr=""
        )
        with patch.dict("os.environ", {"KAGITCH_SHELL_WRAPPER": "1"}), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(mod, "_git_head", return_value=["abc", "old"]), \
             patch.object(mod.subprocess, "run", return_value=mock_success), \
             patch.object(mod, "console") as mock_con:
            rc = mod.cmd_update()
        assert rc == 0
        mock_con.print.assert_called()


# ── Import coverage ──────────────────────────────────────────────


def test_module_imports():
    """Verify all key symbols are importable from the module."""
    assert mod.cmd_shellpath is not None
    assert mod.cmd_init is not None
    assert mod.cmd_completions is not None
    assert mod.cmd_update is not None
    assert mod._reload is not None
    assert mod._git_log is not None
    assert mod._git_head is not None
