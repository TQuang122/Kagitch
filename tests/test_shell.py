"""Tests for shell module."""
import pytest

from kaggle_switch import shell as sh


class TestShellpath:
    def test_zsh_output_contains_function(self):
        result = sh.shellpath("zsh")
        assert "kaggle-switch()" in result
        assert "command kaggle-switch" in result
        assert "KAGGLE_CONFIG_DIR" in result

    def test_bash_output_same_as_zsh(self):
        assert sh.shellpath("bash") == sh.shellpath("zsh")

    def test_fish_output_uses_fish_syntax(self):
        result = sh.shellpath("fish")
        assert "function kaggle-switch" in result
        assert "set -gx KAGGLE_CONFIG_DIR" in result
        assert "end" in result
        assert "command kaggle-switch" in result

    def test_unsupported_shell_raises(self):
        with pytest.raises(ValueError, match="Unsupported shell"):
            sh.shellpath("powershell")

    def test_zsh_function_handles_numeric_arg(self):
        result = sh.shellpath("zsh")
        assert '=~ ^[0-9]+$' in result

    def test_zsh_function_has_marker_parsing(self):
        result = sh.shellpath("zsh")
        assert '__KAGGLE_SWITCH__' in result
        assert '${out#__KAGGLE_SWITCH__}' in result

    def test_fish_function_has_marker_parsing(self):
        result = sh.shellpath("fish")
        assert '__KAGGLE_SWITCH__' in result
        assert 'string replace' in result


class TestDetectShell:
    def test_detect_zsh(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        assert sh.detect_shell() == "zsh"

    def test_detect_bash(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/usr/bin/bash")
        assert sh.detect_shell() == "bash"

    def test_detect_fish(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/usr/local/bin/fish")
        assert sh.detect_shell() == "fish"

    def test_detect_default_when_empty(self, monkeypatch):
        monkeypatch.delenv("SHELL", raising=False)
        assert sh.detect_shell() == "zsh"

    def test_detect_default_when_unknown(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/unknownshell")
        assert sh.detect_shell() == "zsh"


class TestRcFile:
    def test_zsh_rc(self):
        rc = sh.rc_file_for_shell("zsh")
        assert rc is not None
        assert rc.name == ".zshrc"

    def test_bash_rc(self):
        rc = sh.rc_file_for_shell("bash")
        assert rc is not None
        assert rc.name == ".bashrc"

    def test_fish_rc(self):
        rc = sh.rc_file_for_shell("fish")
        assert rc is not None
        assert rc.name == "config.fish"

    def test_unknown_returns_none(self):
        assert sh.rc_file_for_shell("powershell") is None


class TestEvalLine:
    def test_zsh_eval_line(self):
        line = sh.eval_line_for_shell("zsh")
        assert 'eval "$(kaggle-switch shellpath zsh)"' == line

    def test_bash_eval_line(self):
        line = sh.eval_line_for_shell("bash")
        assert 'eval "$(kaggle-switch shellpath zsh)"' == line

    def test_fish_eval_line(self):
        line = sh.eval_line_for_shell("fish")
        assert "source" in line
        assert "kaggle-switch shellpath fish" in line
