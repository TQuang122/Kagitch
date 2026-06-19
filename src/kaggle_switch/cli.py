"""CLI entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from . import __version__
from .config import (
    Account,
    add_account,
    current_active,
    find_account,
    get_accounts,
    load_config,
    remove_account,
    rename_account,
    save_config,
    switch_marker,
)
from .shell import (
    SUPPORTED_SHELLS,
    detect_shell,
    eval_line_for_shell,
    rc_file_for_shell,
    shellpath,
)

USAGE = """\
kaggle-switch — Kaggle multi-account manager

Usage:
    kaggle-switch                 List accounts + show current
    kaggle-switch <N>             Switch to account N
    kaggle-switch list            List all accounts
    kaggle-switch current         Show active account
    kaggle-switch add <name> [kaggle.json path]
                                  Register a new account
    kaggle-switch remove <N|name> Remove an account
    kaggle-switch rename <N> <new_name>
                                  Rename an account
    kaggle-switch shellpath <zsh|bash|fish>
                                  Print shell function for integration
    kaggle-switch init            Auto-install shell integration
    kaggle-switch --version       Show version
    kaggle-switch --help          Show this help
"""


def cmd_list(config: dict) -> int:
    active = current_active(config)
    accounts = get_accounts(config)
    if not accounts:
        print("No accounts configured.")
        print(f"Run: kaggle-switch add <name> /path/to/kaggle.json")
        return 1
    print(f"{'#':<4} {'Name':<20} {'Config Dir':<45} {'Status'}")
    print(f"{'─'*4} {'─'*20} {'─'*45} {'─'*8}")
    for acc in accounts:
        status = "● active" if acc.number == active else ""
        print(f"{acc.number:<4} {acc.name:<20} {str(acc.path):<45} {status}")
    return 0


def cmd_current(config: dict) -> int:
    n = current_active(config)
    if n is None:
        print("No account active (using default ~/.kaggle)")
        return 0
    acc = find_account(config, n)
    if acc:
        print(f"Account {n}: {acc.name}  ({acc.path})")
    else:
        print(f"Account {n}")
    return 0


def cmd_switch(config: dict, key: str) -> int:
    acc = find_account(config, key)
    if acc is None:
        print(f"Account '{key}' not found")
        return 1
    print(switch_marker(acc))
    return 0


def cmd_add(config: dict, args: list[str]) -> int:
    if not args:
        print("Usage: kaggle-switch add <name> [kaggle.json path]")
        return 1
    name = args[0]
    json_path = Path(args[1]) if len(args) >= 2 else None
    try:
        acc = add_account(config, name, json_path)
        print(f"Added account #{acc.number}: {acc.name}  ({acc.path}/)")
        return 0
    except (ValueError, FileNotFoundError) as e:
        print(str(e))
        return 1


def cmd_remove(config: dict, args: list[str]) -> int:
    if not args:
        print("Usage: kaggle-switch remove <N|name>")
        return 1
    try:
        acc = remove_account(config, args[0])
        print(f"Remove account #{acc.number}: {acc.name}? [y/N] ", end="", flush=True)
        resp = sys.stdin.readline().strip().lower()
        if resp == "y":
            print("Removed.")
        else:
            print("Cancelled.")
            # Re-add since we already deleted
            config["accounts"][acc.number] = {"name": acc.name, "config_dir": acc.config_dir}
            save_config(config)
        return 0
    except KeyError as e:
        print(str(e))
        return 1


def cmd_rename(config: dict, args: list[str]) -> int:
    if len(args) < 2:
        print("Usage: kaggle-switch rename <N> <new_name>")
        return 1
    try:
        acc = rename_account(config, args[0], args[1])
        print(f"Renamed #{acc.number}: {acc.name}")
        return 0
    except KeyError as e:
        print(str(e))
        return 1


def cmd_shellpath(args: list[str]) -> int:
    shell = args[0] if args else detect_shell()
    try:
        print(shellpath(shell), end="")
        return 0
    except ValueError as e:
        print(str(e))
        return 1


def cmd_init() -> int:
    shell = detect_shell()
    rc = rc_file_for_shell(shell)
    if rc is None:
        print(f"Cannot detect rc file for shell: {shell}")
        return 1

    eval_line = eval_line_for_shell(shell)

    if rc.exists():
        content = rc.read_text()
        if "kaggle-switch" in content and "shellpath" in content:
            print(f"Shell integration already exists in {rc}")
            print(f"Restart your shell or run: source {rc}")
            return 0

    print(f"Detected shell: {shell}")
    print(f"Adding shell integration to: {rc}")
    rc.parent.mkdir(parents=True, exist_ok=True)
    with open(rc, "a") as f:
        f.write(f"\n# kaggle-switch shell integration\n{eval_line}\n")
    print(f"\nDone! Restart your shell or run:")
    print(f"  source {rc}")
    return 0


def main() -> int:
    config = load_config()
    args = sys.argv[1:]

    if not args:
        return cmd_list(config)

    cmd = args[0]
    rest = args[1:]

    if cmd in ("--help", "-h", "help"):
        print(USAGE)
        return 0

    if cmd in ("--version", "-v"):
        print(f"kaggle-switch {__version__}")
        return 0

    if cmd in ("list", "ls"):
        return cmd_list(config)

    if cmd in ("current", "cur", "."):
        return cmd_current(config)

    if cmd == "switch":
        if not rest:
            print("Usage: kaggle-switch switch <N>")
            return 1
        return cmd_switch(config, rest[0])

    if cmd == "add":
        return cmd_add(config, rest)

    if cmd in ("remove", "rm"):
        return cmd_remove(config, rest)

    if cmd == "rename":
        return cmd_rename(config, rest)

    if cmd == "shellpath":
        return cmd_shellpath(rest)

    if cmd == "init":
        return cmd_init()

    # Shorthand: kaggle-switch <N>
    if cmd.isdigit() or (cmd.startswith("-") and cmd[1:].isdigit()):
        return cmd_switch(config, cmd)

    print(f"Unknown command: {cmd}")
    print(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
