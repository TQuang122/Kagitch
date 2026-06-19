"""CLI entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from . import __version__
from .config import (
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
    detect_shell,
    eval_line_for_shell,
    rc_file_for_shell,
    shellpath,
)
from .style import (
    bordered_table,
    card,
    bold,
    bold_red,
    cyan,
    dim,
    fail,
    info,
    ok,
    pad_to,
    prompt,
    warn,
)

USAGE = f"""\
{bold("kaggle-switch")} — {cyan("Kaggle multi-account manager")}

{bold("Usage:")}
    {cyan("kaggle-switch")}                 List accounts + show current
    {cyan("kaggle-switch")} {bold("<N>")}             Switch to account N
    {cyan("kaggle-switch")} list            List all accounts
    {cyan("kaggle-switch")} current         Show active account
    {cyan("kaggle-switch")} add {bold("<name>")} [{bold("<kaggle.json>")}]
                                  Register a new account
    {cyan("kaggle-switch")} remove {bold("<N|name>")} Remove an account
    {cyan("kaggle-switch")} rename {bold("<N>")} {bold("<new_name>")}
                                  Rename an account
    {cyan("kaggle-switch")} shellpath {bold("<zsh|bash|fish>")}
                                  Print shell function for integration
    {cyan("kaggle-switch")} init            Auto-install shell integration
    {cyan("kaggle-switch")} {dim("--version")}       Show version
    {cyan("kaggle-switch")} {dim("--help")}          Show this help
"""


def cmd_list(config: dict) -> int:
    active = current_active(config)
    accounts = get_accounts(config)
    if not accounts:
        print(warn("No accounts configured."))
        print(f"  Run: {bold("kaggle-switch add <name> /path/to/kaggle.json")}")
        return 1

    headers = ["#", "Name", "Config Dir", "Status"]
    rows: list[list[str]] = []
    active_idx: int | None = None
    for i, acc in enumerate(accounts):
        status = "● active" if acc.number == active else ""
        if acc.number == active:
            active_idx = i
        rows.append([str(acc.number), acc.name, str(acc.path), status])

    print(bordered_table(headers, rows, active_index=active_idx))
    return 0


def cmd_current(config: dict) -> int:
    n = current_active(config)
    if n is None:
        print(warn("No account active (using default ~/.kaggle)"))
        return 0

    acc = find_account(config, n)
    if acc is None:
        print(warn(f"Account {n} not found in config"))
        return 1

    label = "default" if acc.is_default else "custom"
    lines = [
        f"Account #{acc.number}  {bold(acc.name)}",
        "",
        f"  {cyan("\u25b6")}  {acc.path}  ({dim(label)})",
    ]
    print(card(lines, title="Active Account", color=cyan))
    return 0


def cmd_switch(config: dict, key: str) -> int:
    acc = find_account(config, key)
    if acc is None:
        print(fail(f"Account '{key}' not found"))
        return 1
    print(switch_marker(acc))
    return 0


def cmd_add(config: dict, args: list[str]) -> int:
    if not args:
        print(warn("Usage: kaggle-switch add <name> [kaggle.json path]"))
        return 1
    name = args[0]
    json_path = Path(args[1]) if len(args) >= 2 else None
    try:
        acc = add_account(config, name, json_path)
        print(ok(f"Added account #{acc.number}: {acc.name}  ({acc.path}/)"))
        return 0
    except (ValueError, FileNotFoundError) as e:
        print(fail(str(e)))
        return 1


def cmd_remove(config: dict, args: list[str]) -> int:
    if not args:
        print(warn("Usage: kaggle-switch remove <N|name>"))
        return 1
    try:
        acc = remove_account(config, args[0])
        print(prompt(f"Remove account #{acc.number}: {acc.name}?"), end="", flush=True)
        print(" [y/N] ", end="", flush=True)
        resp = sys.stdin.readline().strip().lower()
        if resp == "y":
            print(ok("Removed."))
        else:
            print(dim("Cancelled."))
            # Re-add since we already deleted
            config["accounts"][acc.number] = {"name": acc.name, "config_dir": acc.config_dir}
            save_config(config)
        return 0
    except KeyError as e:
        print(fail(str(e)))
        return 1


def cmd_rename(config: dict, args: list[str]) -> int:
    if len(args) < 2:
        print(warn("Usage: kaggle-switch rename <N> <new_name>"))
        return 1
    try:
        acc = rename_account(config, args[0], args[1])
        print(ok(f"Renamed #{acc.number}: {acc.name}"))
        return 0
    except KeyError as e:
        print(fail(str(e)))
        return 1


def cmd_shellpath(args: list[str]) -> int:
    shell = args[0] if args else detect_shell()
    try:
        print(shellpath(shell), end="")
        return 0
    except ValueError as e:
        print(fail(str(e)))
        return 1


def cmd_init() -> int:
    shell = detect_shell()
    rc = rc_file_for_shell(shell)
    if rc is None:
        print(fail(f"Cannot detect rc file for shell: {shell}"))
        return 1

    eval_line = eval_line_for_shell(shell)

    if rc.exists():
        content = rc.read_text()
        if "kaggle-switch" in content and "shellpath" in content:
            print(info(f"Shell integration already exists in {rc}"))
            print(f"  Restart your shell or run: {bold('source ' + str(rc))}")
            return 0

    print(info(f"Detected shell: {shell}"))
    print(f"  Adding shell integration to: {rc}")
    rc.parent.mkdir(parents=True, exist_ok=True)
    with open(rc, "a") as f:
        f.write(f"\n# kaggle-switch shell integration\n{eval_line}\n")
    print()
    print(ok("Done! Restart your shell or run:"))
    print(f"  {bold('source ' + str(rc))}")
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
        print(cyan(f"kaggle-switch {__version__}"))
        return 0

    if cmd in ("list", "ls"):
        return cmd_list(config)

    if cmd in ("current", "cur", "."):
        return cmd_current(config)

    if cmd == "switch":
        if not rest:
            print(warn("Usage: kaggle-switch switch <N>"))
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

    print(fail(f"Unknown command: {cmd}"))
    print(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
