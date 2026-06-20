"""Shell integration function generation."""
from __future__ import annotations
import sys
from pathlib import Path

SUPPORTED_SHELLS = ("zsh", "bash", "fish", "powershell")

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

_ZSH_BASH_FUNCTION = """\
kagitch() {
  if [[ $# -eq 0 ]]; then
    command kagitch list
    return
  fi

  local known_cmds=" list ls current cur . switch add login remove rm rename patch shellpath init check doctor update completions -h help -v version --help --version "
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
}
"""

_FISH_FUNCTION = """\
function kagitch
  if test (count $argv) -eq 0
    command kagitch list
    return
  end

  set -l known_cmds list ls current cur . switch add login remove rm rename patch shellpath init check doctor update completions -h help -v version --help --version
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


# ── Shell completion generators ───────────────────────────────

_ZSH_COMPLETION = """\
#compdef kagitch
# kagitch shell completion — do not edit manually

__kagitch_accounts() {
  local -a accounts
  while IFS=: read -r num name; do
    accounts+=("$num:$name")
  done < <(command kagitch __list_accounts 2>/dev/null)
  _describe 'account' accounts
}

__kagitch_commands() {
  local -a commands
  commands=(
    'list:List all accounts'
    'ls:Alias for list'
    'current:Show active account'
    'cur:Alias for current'
    'switch:Switch to account N'
    'add:Register a new account'
    'login:Alias for add'
    'remove:Remove an account'
    'rm:Alias for remove'
    'rename:Rename an account'
    'patch:Patch kernel-metadata.json id'
    'shellpath:Print shell function'
    'init:Auto-install shell integration'
    'check:Check account health and quota'
    'doctor:System diagnostics'
    'update:Pull latest version from git'
    'completions:Generate shell completion'
    'help:Show help'
    'version:Show version'
  )
  _describe 'command' commands
}

_kagitch() {
  local curcontext="$curcontext" state state_descs line
  typeset -A opt_args

  _arguments -C \\
    '-v[Show version]' \\
    '--version[Show version]' \\
    '-h[Show help]' \\
    '--help[Show help]' \\
    '1: :->cmd_or_num' \\
    '*:: :->args'

  case $state in
    cmd_or_num)
      _alternative \\
        'accounts:account:__kagitch_accounts' \\
        'commands:command:__kagitch_commands'
      ;;
  esac
}

_kagitch "$@"
"""

_BASH_COMPLETION = """\
# kagitch shell completion — source this file or add to your .bashrc

_kagitch_completions() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local cmds="list ls current cur switch add login remove rm rename patch shellpath init check doctor update completions -h help -v version --help --version"

  if [[ $COMP_CWORD -eq 1 ]]; then
    local -a accounts
    while IFS=: read -r num name; do
      accounts+=("$num" "$name")
    done < <(command kagitch __list_accounts 2>/dev/null)
    COMPREPLY=($(compgen -W "$cmds ${accounts[*]}" -- "$cur"))
  fi
}

complete -F _kagitch_completions kagitch
"""

_FISH_COMPLETION = """\
# kagitch shell completion — do not edit manually

complete -c kagitch -f -n __fish_use_subcommand -a list -d "List all accounts"
complete -c kagitch -f -n __fish_use_subcommand -a ls -d "Alias for list"
complete -c kagitch -f -n __fish_use_subcommand -a current -d "Show active account"
complete -c kagitch -f -n __fish_use_subcommand -a cur -d "Alias for current"
complete -c kagitch -f -n __fish_use_subcommand -a switch -d "Switch to account N"
complete -c kagitch -f -n __fish_use_subcommand -a add -d "Register a new account"
complete -c kagitch -f -n __fish_use_subcommand -a login -d "Alias for add"
complete -c kagitch -f -n __fish_use_subcommand -a remove -d "Remove an account"
complete -c kagitch -f -n __fish_use_subcommand -a rm -d "Alias for remove"
complete -c kagitch -f -n __fish_use_subcommand -a rename -d "Rename an account"
complete -c kagitch -f -n __fish_use_subcommand -a patch -d "Patch kernel-metadata.json id"
complete -c kagitch -f -n __fish_use_subcommand -a shellpath -d "Print shell function"
complete -c kagitch -f -n __fish_use_subcommand -a init -d "Auto-install shell integration"
complete -c kagitch -f -n __fish_use_subcommand -a check -d "Check account health and quota"
complete -c kagitch -f -n __fish_use_subcommand -a doctor -d "System diagnostics"
complete -c kagitch -f -n __fish_use_subcommand -a update -d "Pull latest version from git"
complete -c kagitch -f -n __fish_use_subcommand -a completions -d "Generate shell completion"
complete -c kagitch -f -n __fish_use_subcommand -s v -l version -d "Show version"
complete -c kagitch -f -n __fish_use_subcommand -a version -d "Show version"
complete -c kagitch -f -n __fish_use_subcommand -s h -l help -d "Show help"
complete -c kagitch -f -n __fish_use_subcommand -a help -d "Show help"

# Dynamic account completions for first argument
complete -c kagitch -f -n __fish_use_subcommand -a "(command kagitch __list_accounts 2>/dev/null | string replace : \\t)"
"""

_POWERSHELL_COMPLETION = """\
# kagitch PowerShell completion — add to your $PROFILE

Register-ArgumentCompleter -Native -CommandName kagitch -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $commands = @(
        [System.Management.Automation.CompletionResult]::new('list', 'list', [System.Management.Automation.CompletionResultType]::ParameterValue, 'List all accounts')
        [System.Management.Automation.CompletionResult]::new('ls', 'ls', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Alias for list')
        [System.Management.Automation.CompletionResult]::new('current', 'current', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Show active account')
        [System.Management.Automation.CompletionResult]::new('cur', 'cur', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Alias for current')
        [System.Management.Automation.CompletionResult]::new('switch', 'switch', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Switch to account N')
        [System.Management.Automation.CompletionResult]::new('add', 'add', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Register a new account')
        [System.Management.Automation.CompletionResult]::new('login', 'login', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Alias for add')
        [System.Management.Automation.CompletionResult]::new('remove', 'remove', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Remove an account')
        [System.Management.Automation.CompletionResult]::new('rm', 'rm', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Alias for remove')
        [System.Management.Automation.CompletionResult]::new('rename', 'rename', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Rename an account')
        [System.Management.Automation.CompletionResult]::new('patch', 'patch', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Patch kernel-metadata.json id')
        [System.Management.Automation.CompletionResult]::new('shellpath', 'shellpath', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Print shell function')
        [System.Management.Automation.CompletionResult]::new('init', 'init', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Auto-install shell integration')
        [System.Management.Automation.CompletionResult]::new('check', 'check', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Check account health and quota')
        [System.Management.Automation.CompletionResult]::new('doctor', 'doctor', [System.Management.Automation.CompletionResultType]::ParameterValue, 'System diagnostics')
        [System.Management.Automation.CompletionResult]::new('update', 'update', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Pull latest version from git')
        [System.Management.Automation.CompletionResult]::new('completions', 'completions', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Generate shell completion')
        [System.Management.Automation.CompletionResult]::new('-h', '-h', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Show help')
        [System.Management.Automation.CompletionResult]::new('help', 'help', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Show help')
        [System.Management.Automation.CompletionResult]::new('-v', '-v', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Show version')
        [System.Management.Automation.CompletionResult]::new('version', 'version', [System.Management.Automation.CompletionResultType]::ParameterValue, 'Show version')
    )

    # Dynamic account completions
    $accounts = & "kagitch.exe" __list_accounts 2>&1 | ForEach-Object {
        $num, $name = $_ -split ':'
        [System.Management.Automation.CompletionResult]::new($num, "$num ($name)", [System.Management.Automation.CompletionResultType]::ParameterValue, $name)
    }

    $commands + $accounts | Where-Object {
        $_.CompletionText -like "$wordToComplete*" -or $_.ListItemText -like "$wordToComplete*"
    }
}
"""


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
