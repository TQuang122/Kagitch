"""Shell integration function generation."""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SHELLS = ("zsh", "bash", "fish", "powershell")


# ── Single source of truth for all commands/aliases/flags ──────

@dataclass
class _CmdDef:
    desc: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class _FlagDef:
    desc: str
    short: str | None = None


_COMMANDS: dict[str, _CmdDef] = {
    "list":        _CmdDef("List all accounts",                  ["ls"]),
    "current":     _CmdDef("Show active account",               ["cur", "."]),
    "switch":      _CmdDef("Switch to account N"),
    "add":         _CmdDef("Register a new account",            ["login"]),
    "remove":      _CmdDef("Remove an account",                 ["rm"]),
    "rename":      _CmdDef("Rename an account"),
    "patch":       _CmdDef("Patch kernel-metadata.json id"),
    "shellpath":   _CmdDef("Print shell function"),
    "init":        _CmdDef("Auto-install shell integration"),
    "check":       _CmdDef("Check account health and quota"),
    "doctor":      _CmdDef("System diagnostics"),
    "update":      _CmdDef("Pull latest version from git"),
    "completions": _CmdDef("Generate shell completion"),
    "help":        _CmdDef("Show help"),
    "version":     _CmdDef("Show version"),
}

_FLAGS: dict[str, _FlagDef] = {
    "help":    _FlagDef("Show help", "-h"),
    "version": _FlagDef("Show version", "-v"),
}


# ── Generation helpers ─────────────────────────────────────────

def _all_known_tokens() -> list[str]:
    """Every token the shell wrapper should accept as a known command."""
    tokens: list[str] = []
    for cmd, defn in _COMMANDS.items():
        tokens.append(cmd)
        tokens.extend(a for a in defn.aliases)
    for flag_name, defn in _FLAGS.items():
        if defn.short:
            tokens.append(defn.short)
        tokens.append(f"--{flag_name}")
    return tokens


def _build_cmds_str() -> str:
    return " ".join(_all_known_tokens())


def _zsh_cmds_block() -> str:
    lines: list[str] = []
    for cmd, defn in _COMMANDS.items():
        lines.append(f"    '{cmd}:{defn.desc}'")
        for alias in defn.aliases:
            lines.append(f"    '{alias}:Alias for {cmd}'")
    return "\n".join(lines)


def _zsh_flags_block() -> str:
    lines: list[str] = []
    for flag_name, defn in _FLAGS.items():
        if defn.short:
            lines.append(f"    '{defn.short}[{defn.desc}]' \\")
        lines.append(f"    '--{flag_name}[{defn.desc}]' \\")
    return "\n".join(lines)


def _fish_cmds_block() -> str:
    lines: list[str] = []
    for cmd, defn in _COMMANDS.items():
        lines.append(f'complete -c kagitch -f -n __fish_use_subcommand -a {cmd} -d "{defn.desc}"')
        for alias in defn.aliases:
            lines.append(f'complete -c kagitch -f -n __fish_use_subcommand -a {alias} -d "Alias for {cmd}"')
    for flag_name, defn in _FLAGS.items():
        parts = ["complete -c kagitch -f -n __fish_use_subcommand"]
        if defn.short:
            parts.append(f"-s {defn.short.lstrip('-')}")
        parts.append(f"-l {flag_name}")
        parts.append(f'-d "{defn.desc}"')
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _ps_cmds_block() -> str:
    lines: list[str] = []
    for cmd, defn in _COMMANDS.items():
        lines.append(_ps_result(cmd, cmd, defn.desc))
        for alias in defn.aliases:
            lines.append(_ps_result(alias, alias, f"Alias for {cmd}"))
    for flag_name, defn in _FLAGS.items():
        if defn.short:
            lines.append(_ps_result(defn.short, defn.short, defn.desc))
        lines.append(_ps_result(flag_name, flag_name, defn.desc))
    return "\n".join(lines)


def _ps_result(completion: str, list_item: str, desc: str) -> str:
    return (
        f"        [System.Management.Automation.CompletionResult]::new("
        f"'{completion}', '{list_item}', "
        f"[System.Management.Automation.CompletionResultType]::ParameterValue, "
        f"'{desc}')"
    )


# ── Shell wrapper functions ────────────────────────────────────

_KNOWN_CMDS_STR = _build_cmds_str()

_POWERSHELL_FUNCTION = """\
function Invoke-Kagitch {
    param([Parameter(ValueFromRemainingArguments)][string[]]$Arguments)
    $output = & "kagitch.exe" @Arguments 2>&1 | Out-String -Stream
    foreach ($line in $output) {
        if ($line -match '^export KAGGLE_CONFIG_DIR=(.*)') {
            $env:KAGGLE_CONFIG_DIR = $matches[1]
        } elseif ($line -match '^unset KAGGLE_CONFIG_DIR') {
            Remove-Item Env:\\KAGGLE_CONFIG_DIR -ErrorAction SilentlyContinue
        } elseif ($line -match '^export KAGGLE_API_TOKEN=(.*)') {
            $env:KAGGLE_API_TOKEN = $matches[1]
        } elseif ($line -match '^unset KAGGLE_API_TOKEN') {
            Remove-Item Env:\\KAGGLE_API_TOKEN -ErrorAction SilentlyContinue
        } else {
            Write-Output $line
        }
    }
}

Set-Alias -Name kagitch -Value Invoke-Kagitch -Scope Global -Option AllScope
"""

_ZSH_BASH_FUNCTION = f"""\
kagitch() {{
  if [[ $# -eq 0 ]]; then
    command kagitch list
    return
  fi

  local known_cmds=" {_KNOWN_CMDS_STR} "
  if [[ "$known_cmds" =~ " $1 " ]]; then
    command kagitch "$@"
  else
    local out
    out=$(command kagitch switch "$1" 2>&1)
    local rc=$?
    if [[ $rc -ne 0 ]]; then
      echo "$out"
      return $rc
    fi
    while IFS= read -r line; do
      if [[ "$line" == "unset "* ]]; then
        eval "$line"
      elif [[ "$line" == "export "* ]]; then
        eval "$line"
      else
        echo "$line"
      fi
    done <<< "$out"
  fi
}}
"""

_FISH_FUNCTION = f"""\
function kagitch
  if test (count $argv) -eq 0
    command kagitch list
    return
  end

  set -l known_cmds {_KNOWN_CMDS_STR}
  if contains -- $argv[1] $known_cmds
    command kagitch $argv
  else
    set out (command kagitch switch $argv[1] 2>&1)
    set rc $status
    if test $rc -ne 0
      echo "$out"
      return $rc
    end
    echo "$out" | while read -l line
      switch "$line"
        case "unset KAGGLE_CONFIG_DIR"
          set -e KAGGLE_CONFIG_DIR
        case "export KAGGLE_CONFIG_DIR="*
          set -gx KAGGLE_CONFIG_DIR (string split -m1 "=" -- "$line")[2]
        case "unset KAGGLE_API_TOKEN"
          set -e KAGGLE_API_TOKEN
        case "export KAGGLE_API_TOKEN="*
          set -gx KAGGLE_API_TOKEN (string split -m1 "=" -- "$line")[2]
        case '*'
          echo "$line"
      end
    end
  end
end
"""


# ── Shell completion generators ───────────────────────────────

_ZSH_CMDS_BLOCK = _zsh_cmds_block()
_ZSH_FLAGS_BLOCK = _zsh_flags_block()
_FISH_CMDS_BLOCK = _fish_cmds_block()
_PS_CMDS_BLOCK = _ps_cmds_block()

_ZSH_COMPLETION = f"""\
#compdef kagitch
# kagitch shell completion — do not edit manually

__kagitch_accounts() {{
  local -a accounts
  while IFS=: read -r num name; do
    accounts+=("$num:$name")
  done < <(command kagitch __list_accounts 2>/dev/null)
  _describe 'account' accounts
}}

__kagitch_commands() {{
  local -a commands
  commands=(
{_ZSH_CMDS_BLOCK}
  )
  _describe 'command' commands
}}

_kagitch() {{
  local curcontext="$curcontext" state state_descs line
  typeset -A opt_args

  _arguments -C \\
{_ZSH_FLAGS_BLOCK}    '1: :->cmd_or_num' \\
    '*:: :->args'

  case $state in
    cmd_or_num)
      _alternative \\
        'accounts:account:__kagitch_accounts' \\
        'commands:command:__kagitch_commands'
      ;;
  esac
}}

_kagitch "$@"
"""

_BASH_COMPLETION = f"""\
# kagitch shell completion — source this file or add to your .bashrc

_kagitch_completions() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}"
  local cmds="{_KNOWN_CMDS_STR}"

  if [[ $COMP_CWORD -eq 1 ]]; then
    local -a accounts
    while IFS=: read -r num name; do
      accounts+=("$num" "$name")
    done < <(command kagitch __list_accounts 2>/dev/null)
    COMPREPLY=($(compgen -W "$cmds ${{accounts[*]}}" -- "$cur"))
  fi
}}

complete -F _kagitch_completions kagitch
"""

_FISH_COMPLETION = f"""\
# kagitch shell completion — do not edit manually

{_FISH_CMDS_BLOCK}

# Dynamic account completions for first argument
complete -c kagitch -f -n __fish_use_subcommand -a "(command kagitch __list_accounts 2>/dev/null | string replace : \\\\t)"
"""

_POWERSHELL_COMPLETION = f"""\
# kagitch PowerShell completion — add to your $PROFILE

Register-ArgumentCompleter -Native -CommandName kagitch -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)

    $commands = @(
{_PS_CMDS_BLOCK}
    )

    # Dynamic account completions
    $accounts = & "kagitch.exe" __list_accounts 2>&1 | ForEach-Object {{
        $num, $name = $_ -split ':'
        [System.Management.Automation.CompletionResult]::new($num, "$num ($name)", [System.Management.Automation.CompletionResultType]::ParameterValue, $name)
    }}

    $commands + $accounts | Where-Object {{
        $_.CompletionText -like "$wordToComplete*" -or $_.ListItemText -like "$wordToComplete*"
    }}
}}
"""


# ── Public API ─────────────────────────────────────────────────

def shellpath(shell: str) -> str:
    """Return the shell function for the given shell type."""
    if shell in ("zsh", "bash"):
        return _ZSH_BASH_FUNCTION
    if shell == "fish":
        return _FISH_FUNCTION
    if shell == "powershell":
        return _POWERSHELL_FUNCTION
    raise ValueError(f"Unsupported shell: {shell!r}. Supported: {', '.join(SUPPORTED_SHELLS)}")


def detect_shell() -> str:
    """Detect the current shell from SHELL env var or platform."""
    shell_path = __import__("os").environ.get("SHELL", "")
    name = Path(shell_path).name.lower() if shell_path else ""
    if "zsh" in name:
        return "zsh"
    if "bash" in name:
        return "bash"
    if "fish" in name:
        return "fish"
    if "pwsh" in name or "powershell" in name:
        return "powershell"
    # On Windows with no SHELL set, default to PowerShell
    if sys.platform == "win32":
        return "powershell"
    return "zsh"


def rc_file_for_shell(shell: str) -> Path | None:
    """Return the rc file path for the given shell, or None if unknown."""
    home = Path.home()
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "bash":
        return home / ".bashrc"
    if shell == "fish":
        return home / ".config" / "fish" / "config.fish"
    if shell == "powershell":
        if sys.platform == "win32":
            return home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
        return home / ".config" / "powershell" / "Microsoft.PowerShell_profile.ps1"
    return None


def eval_line_for_shell(shell: str) -> str:
    """Return the eval line to add to rc file."""
    if shell == "fish":
        return 'kagitch shellpath fish | source'
    if shell == "powershell":
        return 'kagitch shellpath powershell | Out-String | Invoke-Expression'
    return 'eval "$(kagitch shellpath zsh)"'


def completions(shell: str) -> str:
    """Return shell completion script for the given shell."""
    if shell == "zsh":
        return _ZSH_COMPLETION
    if shell == "bash":
        return _BASH_COMPLETION
    if shell == "fish":
        return _FISH_COMPLETION
    if shell == "powershell":
        return _POWERSHELL_COMPLETION
    raise ValueError(f"Unsupported shell: {shell!r}. Supported: {', '.join(SUPPORTED_SHELLS)}")
