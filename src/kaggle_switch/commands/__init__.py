"""Command handler modules."""
from __future__ import annotations

from .accounts import (
    cmd_add,
    cmd_current,
    cmd_dashboard,
    cmd_list,
    cmd_list_accounts,
    cmd_remove,
    cmd_rename,
)
from .doctor import cmd_check, cmd_doctor
from .kernel import _kernel_init_help, cmd_kernel_init, cmd_kernel_logs, cmd_patch
from .setup import cmd_completions, cmd_init, cmd_shellpath, cmd_update
from .switch import cmd_switch, cmd_switch_prompt

__all__ = [
    "_kernel_init_help",
    "cmd_add",
    "cmd_check",
    "cmd_completions",
    "cmd_current",
    "cmd_dashboard",
    "cmd_doctor",
    "cmd_init",
    "cmd_kernel_init",
    "cmd_kernel_logs",
    "cmd_list",
    "cmd_list_accounts",
    "cmd_patch",
    "cmd_remove",
    "cmd_rename",
    "cmd_shellpath",
    "cmd_switch",
    "cmd_switch_prompt",
    "cmd_update",
]
