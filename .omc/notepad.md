# Notepad
<!-- Auto-managed by OMC. Manual edits preserved in MANUAL section. -->

## Priority Context
<!-- ALWAYS loaded. Keep under 500 chars. Critical discoveries only. -->
Kaggle Switch (kagitch) — Cursor shell wrapper reload fix

## Context
The shell wrapper (`bin/after/kagitch`) captures stdout/stderr to a temp file so Cursor/IDE can display output. `kagitch init -r` calls `_reload()` which uses `os.execvp("zsh", ["zsh", "-l"])` — but the new shell inherits the redirected fds, runs non-interactively, and exits immediately (you only see a blank terminal).

## Analysis
1. `_reload()` at `cli.py:816` exec's a new login shell so source+alias take effect in the same terminal
2. Shell wrapper's `KAGITCH_SHELL_WRAPPER=1` + temp-file redirect on fd 1/2 is inherited through exec
3. New shell detects non-TTY stdout, skips `.zshrc` interactive sections, exits

## Fix applied
Added a check at `cli.py:845`: when `KAGITCH_SHELL_WRAPPER` is set, redirect stdout/stderr back to `/dev/tty` before exec, then create a fresh Rich Console pointing at the terminal. Also flush both fds before exec to prevent buffer loss.

## Remaining
- All 204 tests pass, no new diagnostics
- Pending `kagitch init -r` end-to-end verification inside Cursor terminal (cannot test programmatically — requires real PTY)


## Working Memory
<!-- Session notes. Auto-pruned after 7 days. -->

## MANUAL
<!-- User content. Never auto-pruned. -->

