"""Shell integration function generation."""
from __future__ import annotations

SUPPORTED_SHELLS = ("zsh", "bash", "fish")

_ZSH_BASH_FUNCTION = """\
kaggle-switch() {
  if [[ $# -eq 0 ]]; then
    command kaggle-switch list
    return
  fi

  if [[ "$1" =~ ^[0-9]+$ ]]; then
    local out
    out=$(command kaggle-switch switch "$1" 2>&1)
    local rc=$?
    if [[ "$out" == "__KAGGLE_SWITCH__" ]]; then
      unset KAGGLE_CONFIG_DIR
      echo "Switched to account $1"
    elif [[ "$out" == __KAGGLE_SWITCH__* ]]; then
      export KAGGLE_CONFIG_DIR="${out#__KAGGLE_SWITCH__}"
      echo "Switched to account $1"
    else
      echo "$out"
      return $rc
    fi
  else
    command kaggle-switch "$@"
  fi
}
"""

_FISH_FUNCTION = """\
function kaggle-switch
  if test (count $argv) -eq 0
    command kaggle-switch list
    return
  end

  if string match -qr '^[0-9]+$' -- $argv[1]
    set out (command kaggle-switch switch $argv[1] 2>&1)
    set rc $status
    if test "$out" = "__KAGGLE_SWITCH__"
      set -e KAGGLE_CONFIG_DIR
      echo "Switched to account $argv[1]"
    else if string match -q "__KAGGLE_SWITCH__*" -- $out
      set -gx KAGGLE_CONFIG_DIR (string replace "__KAGGLE_SWITCH__" "" -- $out)
      echo "Switched to account $argv[1]"
    else
      echo "$out"
      return $rc
    end
  else
    command kaggle-switch $argv
  end
end
"""


def shellpath(shell: str) -> str:
    """Return the shell function for the given shell type."""
    if shell in ("zsh", "bash"):
        return _ZSH_BASH_FUNCTION
    if shell == "fish":
        return _FISH_FUNCTION
    raise ValueError(f"Unsupported shell: {shell!r}. Supported: {', '.join(SUPPORTED_SHELLS)}")


def detect_shell() -> str:
    """Detect the current shell from SHELL env var."""
    import os
    shell_path = os.environ.get("SHELL", "")
    name = Path(shell_path).name.lower() if shell_path else ""
    if "zsh" in name:
        return "zsh"
    if "bash" in name:
        return "bash"
    if "fish" in name:
        return "fish"
    return "zsh"  # default


def rc_file_for_shell(shell: str) -> Path | None:
    """Return the rc file path for the given shell, or None if unknown."""
    home = Path.home()
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "bash":
        return home / ".bashrc"
    if shell == "fish":
        return home / ".config" / "fish" / "config.fish"
    return None


def eval_line_for_shell(shell: str) -> str:
    """Return the eval line to add to rc file."""
    if shell == "fish":
        return 'kaggle-switch shellpath fish | source'
    return 'eval "$(kaggle-switch shellpath zsh)"'
