"""Tests for shell module."""
import pytest

from kaggle_switch import shell as sh


class TestShellpath:
    def test_zsh_output_contains_function(self):
        result = sh.shellpath("zsh")
        assert "kagitch()" in result
        assert "command kagitch" in result
        assert "eval" in result

    def test_bash_output_same_as_zsh(self):
        assert sh.shellpath("bash") == sh.shellpath("zsh")

    def test_fish_output_uses_fish_syntax(self):
        result = sh.shellpath("fish")
        assert "function kagitch" in result
        assert "set -gx KAGGLE_CONFIG_DIR" in result
        assert "end" in result
        assert "command kagitch" in result

    def test_powershell_output_contains_function(self):
        result = sh.shellpath("powershell")
        assert "Invoke-Kagitch" in result
        assert "Set-Alias" in result
        assert "KAGGLE_CONFIG_DIR" in result

    def test_unsupported_shell_raises(self):
        with pytest.raises(ValueError, match="Unsupported shell"):
            sh.shellpath("tcsh")

    def test_zsh_function_handles_numeric_arg(self):
        result = sh.shellpath("zsh")
        assert 'known_cmds=' in result

    def test_shell_functions_route_aliases_as_commands(self):
        for shell in ("zsh", "fish"):
            result = sh.shellpath(shell)
            for alias in ("ls", "cur", ".", "rm", "login", "-h", "help", "-v", "version"):
                assert alias in result

    def test_zsh_function_has_env_parsing(self):
        result = sh.shellpath("zsh")
        assert 'KAGITCH_SHELL_WRAPPER=1' in result
        assert 'while IFS= read -r line' in result
        assert '== "unset "* ]]' in result
        assert '== "export "* ]]' in result

    def test_fish_function_has_env_parsing(self):
        result = sh.shellpath("fish")
        assert 'KAGITCH_SHELL_WRAPPER=1' in result
        assert 'KAGGLE_CONFIG_DIR' in result
        assert 'KAGGLE_API_TOKEN' in result
        assert 'set -e' in result

    def test_powershell_function_has_env_parsing(self):
        result = sh.shellpath("powershell")
        assert 'KAGITCH_SHELL_WRAPPER' in result
        assert 'KAGGLE_CONFIG_DIR' in result
        assert 'KAGGLE_API_TOKEN' in result
        assert 'Remove-Item' in result


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

    def test_detect_pwsh(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/usr/local/bin/pwsh")
        assert sh.detect_shell() == "powershell"

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

    def test_powershell_rc(self):
        rc = sh.rc_file_for_shell("powershell")
        assert rc is not None
        assert "PowerShell_profile" in str(rc.name)

    def test_unknown_returns_none(self):
        assert sh.rc_file_for_shell("tcsh") is None


class TestEvalLine:
    def test_zsh_eval_line(self):
        line = sh.eval_line_for_shell("zsh")
        assert 'eval "$(kagitch shellpath zsh)"' == line

    def test_bash_eval_line(self):
        line = sh.eval_line_for_shell("bash")
        assert 'eval "$(kagitch shellpath zsh)"' == line

    def test_fish_eval_line(self):
        line = sh.eval_line_for_shell("fish")
        assert "source" in line
        assert "kagitch shellpath fish" in line

    def test_powershell_eval_line(self):
        line = sh.eval_line_for_shell("powershell")
        assert "Invoke-Expression" in line or "Out-String" in line
        assert "kagitch shellpath powershell" in line


class TestCompletions:
    def test_completions_zsh(self):
        result = sh.completions("zsh")
        assert "#compdef" in result
        assert "_kagitch" in result
        assert "__kagitch_accounts" in result
        assert "list" in result
        assert "check" in result
        assert "completions" in result

    def test_completions_bash(self):
        result = sh.completions("bash")
        assert "_kagitch_completions" in result
        assert "complete -F" in result
        assert "check" in result

    def test_completions_fish(self):
        result = sh.completions("fish")
        assert "# kagitch" in result
        assert "complete -c kagitch" in result
        assert "check" in result
        assert "completions" in result

    def test_completions_powershell(self):
        result = sh.completions("powershell")
        assert "Register-ArgumentCompleter" in result
        assert "kagitch" in result
        assert "check" in result
        assert "completions" in result


    def test_completions_include_aliases(self):
        aliases = ("ls", "cur", "rm", "login", "help", "version", "update")
        for shell in ("zsh", "bash", "fish", "powershell"):
            result = sh.completions(shell)
            for alias in aliases:
                assert alias in result

        zsh = sh.completions("zsh")
        bash = sh.completions("bash")
        powershell = sh.completions("powershell")
        for result in (zsh, bash, powershell):
            assert "-h" in result
            assert "-v" in result

        fish = sh.completions("fish")
        assert "-s h" in fish
        assert "-s v" in fish

    def test_completions_unsupported_shell(self):
        with pytest.raises(ValueError, match="Unsupported shell"):
            sh.completions("tcsh")

    def test_completions_zsh_has_list_accounts_call(self):
        result = sh.completions("zsh")
        assert "__list_accounts" in result
