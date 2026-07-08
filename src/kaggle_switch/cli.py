"""CLI entry point — thin dispatch layer."""
from __future__ import annotations

import sys

from rich.traceback import Traceback

from . import display
from .commands import (
    _kernel_init_help,
    cmd_add,
    cmd_check,
    cmd_completions,
    cmd_current,
    cmd_dashboard,
    cmd_doctor,
    cmd_init,
    cmd_kernel_init,
    cmd_kernel_logs,
    cmd_list,
    cmd_list_accounts,
    cmd_patch,
    cmd_remove,
    cmd_rename,
    cmd_shellpath,
    cmd_switch,
    cmd_switch_prompt,
    cmd_update,
)
from .config import find_account, load_config
from .style import console, err


def main() -> int:
    try:
        return _main()
    except Exception:
        console.print()
        console.print(Traceback(width=None))
        return 1


def _main() -> int:
    from rich.traceback import install as _install_tb

    _install_tb(show_locals=True, width=None)

    config = load_config()
    args = sys.argv[1:]

    if not args:
        return cmd_dashboard(config)

    cmd = args[0]
    rest = args[1:]

    if cmd in ("--help", "-h", "help"):
        display.render_help()
        return 0

    if cmd in ("--version", "-v", "version"):
        display._render_banner()
        return 0

    if cmd in ("list", "ls"):
        return cmd_list(config)

    if cmd in ("current", "cur", "."):
        return cmd_current(config)

    if cmd == "switch":
        if not rest:
            return cmd_switch_prompt(config)
        return cmd_switch(config, rest[0])

    if cmd in ("add", "login"):
        return cmd_add(config, rest)

    if cmd in ("remove", "rm"):
        return cmd_remove(config, rest)

    if cmd == "rename":
        return cmd_rename(config, rest)

    if cmd == "shellpath":
        return cmd_shellpath(rest)

    if cmd == "init":
        return cmd_init(rest)

    if cmd == "check":
        return cmd_check(config)

    if cmd == "update":
        return cmd_update()

    if cmd == "patch":
        return cmd_patch(config, rest)

    if cmd == "kernel":
        if rest and rest[0] == "init":
            if len(rest) > 1 and rest[1] in ("--help", "-h", "help"):
                _kernel_init_help()
                return 0
            return cmd_kernel_init(config, rest[1:])
        if rest and rest[0] == "logs":
            return cmd_kernel_logs(config, rest[1:])
        console.print(err("Usage: kagitch kernel init | kernel logs <kernel>"))
        return 1

    if cmd == "doctor":
        return cmd_doctor(config)

    if cmd == "completions":
        return cmd_completions(rest)

    if cmd == "__list_accounts":
        return cmd_list_accounts(config)

    # Shorthand: kagitch <N> or <name>
    if (cmd.isdigit() or (cmd.startswith("-") and cmd[1:].isdigit())) or find_account(config, cmd) is not None:
        return cmd_switch(config, cmd)

    console.print(err(f"Unknown command: {cmd}"))
    display.render_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
