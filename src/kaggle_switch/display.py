"""Display utilities — banner, help, Rich rendering helpers.

All display/UI functions extracted from :mod:`cli.py` so the CLI module
stays focused on command orchestration.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import Account, current_active, find_account, get_accounts
from .style import (
    C_DIM,
    C_ERROR,
    C_OK,
    C_WARN,
    card,
    console,
    err,
    info,
)

# ── TTY status ──────────────────────────────────────────────────


@contextmanager
def _tty_status(msg: str):
    """Rich live status via /dev/tty, for wrapper mode. Falls back silently."""
    f = None
    try:
        f = open("/dev/tty", "w")
        tc = Console(file=f, force_terminal=True)
        with tc.status(msg, spinner="dots"):
            yield
    except OSError:
        yield
    finally:
        if f:
            try:
                f.close()
            except Exception:
                pass


# ── Banner ──────────────────────────────────────────────────────


_BANNER_TEXT = "\n".join([
    "██╗  ██╗ █████╗  ██████╗ ██╗████████╗ ██████╗██╗  ██╗",
    "██║ ██╔╝██╔══██╗██╔════╝ ██║╚══██╔══╝██╔════╝██║  ██║",
    "█████╔╝ ███████║██║  ███╗██║   ██║   ██║     ███████║",
    "██╔═██╗ ██╔══██║██║   ██║██║   ██║   ██║     ██╔══██║",
    "██║  ██╗██║  ██║╚██████╔╝██║   ██║   ╚██████╗██║  ██║",
    "╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝",
])


def _render_banner() -> None:
    subtitle = f"        Kaggle multi-account manager \u00b7 v{__version__}"
    banner = _BANNER_TEXT + "\n" + subtitle
    console.print(
        Panel.fit(
            Text(banner, justify="center"),
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()


# ── Help page ───────────────────────────────────────────────────


def render_help() -> None:
    _render_banner()
    console.print("[bold]Usage:[/bold]")
    console.print('  [green]kagitch[/] [cyan]<command>[/] [dim]\\[options]')
    console.print()

    def _cmd_rows(rows: list[tuple[str, str]]) -> str:
        return "\n".join(f"  [green]{cmd:<30}[/] [white]{desc}[/]" for cmd, desc in rows)

    sections = {
        "left": {
            "Account": [
                ("kagitch", "Show dashboard + active account"),
                ("kagitch <N|name>", "Switch to account"),
                ("kagitch switch [N|name]", "Prompt or switch to account"),
                ("kagitch list", "List accounts"),
                ("kagitch current", "Show active account"),
            ],
            "Health": [
                ("kagitch check", "Check health + quota for all accounts"),
                ("kagitch doctor", "System diagnostics"),
                ("kagitch update", "Pull latest version from git"),
            ],
        },
        "right": {
            "Management": [
                ("kagitch add <name> [kaggle.json]", "Register a new account"),
                ("kagitch remove <N|name>", "Remove an account"),
                ("kagitch rename <N> <new_name>", "Rename an account"),
                ("kagitch patch [path]", "Patch kernel-metadata.json id"),
                ("kagitch kernel init", "Create kernel-metadata.json"),
            ],
            "Shell integration": [
                ("kagitch init [-r]", "Interactive setup wizard (7-step)"),
                ("kagitch shellpath <shell>", "Print shell function"),
                ("kagitch completions <shell>", "Print shell completion script"),
            ],
            "Other": [
                ("kagitch --version", "Show version"),
                ("kagitch --help", "Show help"),
            ],
        },
    }

    def _build_body(col: dict) -> str:
        parts: list[str] = []
        for title, rows in col.items():
            parts.append(f"[bold]{title}[/]")
            parts.append(_cmd_rows(rows))
            parts.append("")
        return "\n".join(parts[:-1])  # drop trailing blank

    def _pad_body(body: str, target_lines: int) -> str:
        lines = body.split("\n")
        if len(lines) < target_lines:
            lines.extend([""] * (target_lines - len(lines)))
        return "\n".join(lines)

    left_body = _build_body(sections["left"])
    right_body = _build_body(sections["right"])
    target = max(len(left_body.split("\n")), len(right_body.split("\n")))
    left_body = _pad_body(left_body, target)
    right_body = _pad_body(right_body, target)

    main = Table.grid(padding=(0, 2))
    main.add_column()
    main.add_column()
    main.add_row(
        Panel(left_body, border_style="bright_black", padding=(0, 1)),
        Panel(right_body, border_style="bright_black", padding=(0, 1)),
    )
    console.print(main)

    console.print()
    console.print("[bold]Options:[/bold]")
    console.print("  [cyan]-r, --reload[/]   Reload shell after init (. $PROFILE on PowerShell)")

    console.print()
    console.print("[bold]Examples:[/bold]")
    console.print("  [green]kagitch 2[/]")
    console.print("  [green]kagitch test123[/]")
    console.print("  [green]kagitch check[/]")


# ── Auth method helpers ─────────────────────────────────────────


def _auth_method(path: Path) -> str:
    json_file = path / "kaggle.json"
    if json_file.exists():
        try:
            data = json.loads(json_file.read_text())
            if "username" in data and "key" in data:
                return "Legacy Key"
        except (json.JSONDecodeError, OSError):
            pass
        return "kaggle.json"
    if (path / "access_token").exists():
        return "Token"
    if (path / "credentials.json").exists():
        return "OAuth"
    return "No creds"


def _render_auth(method: str, ok: bool = True) -> str:
    """Auth badge string with icon and color.

    Handles both :func:`_auth_method` output (``"Legacy Key"``,
    ``"OAuth"``) and :attr:`CheckResult.auth_method <kaggle_switch.checker.CheckResult.auth_method>`
    (``"LEGACY_API_KEY"``, ``"OAUTH"``).
    """
    if not ok:
        return f"[{C_ERROR}]\u2717 Failed[/]"
    m = method.upper().replace(" ", "_").rstrip("_")
    if m in ("OAUTH",):
        return f"[{C_OK}]\u2713[/] OAuth"
    if m in ("ACCESS_TOKEN", "TOKEN"):
        return f"[{C_OK}]\u2713[/] Token"
    if m in ("LEGACY_API_KEY", "LEGACY_KEY", "LEGACY"):
        return f"[{C_WARN}]\u26a0[/] Legacy Key"
    if method and method != "No creds":
        return f"[{C_DIM}]? {method}[/]"
    return f"[{C_OK}]\u2713[/]"


# ── Quota helpers ───────────────────────────────────────────────


def _parse_quota(h: str) -> float | None:
    """Parse '4.13h' \u2192 4.13, return None on failure."""
    if not h:
        return None
    try:
        return float(h.rstrip("hH"))
    except (ValueError, AttributeError):
        return None


def _render_quota(hours_str: str) -> str:
    """Color-coded quota display."""
    h = _parse_quota(hours_str)
    if h is None:
        return f"[{C_DIM}]\u2014[/]"
    if h < 1:
        return f"[{C_ERROR}]{hours_str}[/]"
    if h < 5:
        return f"[{C_WARN}]{hours_str}[/]"
    return f"[{C_OK}]{hours_str}[/]"


# ── Terminal helpers ────────────────────────────────────────────


def _terminal_select(
    options: list[str],
    default_index: int = 0,
) -> int | None:
    """Arrow-key navigable terminal selection list.

    Shows options on stderr so it works in both normal and shell-wrapper mode.
    Handles up/down/enter/escape/ctrl+c/q.

    Args:
        options: Display strings for each option.
        default_index: Index to highlight initially (0-based).

    Returns:
        Selected index (0-based), or None if cancelled.
    """
    n = len(options)
    if n == 0:
        return None
    if n == 1:
        return 0

    sel = max(0, min(default_index, n - 1))

    # Open /dev/tty for interactive output when stderr is redirected
    # (shell wrapper mode redirects stderr to a temp file)
    tty_out = None
    out = sys.stderr
    if not sys.stderr.isatty():
        try:
            tty_out = open("/dev/tty", "w")
            out = tty_out
        except OSError:
            pass

    def _lines() -> list[str]:
        return [
            f"  \u25b6 {opt}" if i == sel else f"    {opt}"
            for i, opt in enumerate(options)
        ]

    def _draw(lines: list[str]) -> None:
        for l in lines:
            out.write(f"\r\x1b[K{l}\n")
        out.flush()

    def _cleanup(nlines: int) -> None:
        out.write(f"\x1b[{nlines}A\x1b[J")
        out.flush()

    try:
        import termios
        import tty
    except ImportError:
        if tty_out:
            tty_out.close()
        return default_index if 0 <= default_index < n else 0

    if not sys.stdin.isatty():
        if tty_out:
            tty_out.close()
        return default_index if 0 <= default_index < n else 0

    fd = sys.stdin.fileno()
    old_attr = termios.tcgetattr(fd)
    cur_lines: list[str] = []

    try:
        tty.setraw(fd)
        cur_lines = _lines()
        _draw(cur_lines)

        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                rest = sys.stdin.read(2)
                if rest == "[A":
                    sel = (sel - 1) % n
                elif rest == "[B":
                    sel = (sel + 1) % n
                else:
                    continue
            elif ch in ("\r", "\n"):
                break
            elif ch == "\x03":
                raise KeyboardInterrupt
            elif ch in ("q",):
                sel = -1
                break
            else:
                continue

            _cleanup(len(cur_lines))
            cur_lines = _lines()
            _draw(cur_lines)
    except (KeyboardInterrupt, EOFError):
        sel = -1
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attr)
        if cur_lines:
            _cleanup(len(cur_lines))
        if tty_out:
            tty_out.close()

    return None if sel < 0 else sel


def _select_account_interactive(config: dict) -> Account | None:
    """Prompt user to pick an account (arrow keys in TTY, fallback prompt in pipes)."""
    accounts = get_accounts(config)
    if not accounts:
        console.print(err("No accounts configured - use [bold]kagitch add <name>[/]"))
        return None

    active = current_active(config)

    card_options: list[str] = []
    select_options: list[str] = []
    for acc in accounts:
        label = f"{acc.number}. {acc.name}"
        card_label = label
        if acc.number == active:
            card_label += f"  [{C_OK}]active[/]"
        card_options.append(card_label)
        if acc.number == active:
            select_options.append(f"{label} (active)")
        else:
            select_options.append(label)

    active_idx = 0
    for i, acc in enumerate(accounts):
        if acc.number == active:
            active_idx = i
            break

    if sys.stdin.isatty():
        idx = _terminal_select(select_options, default_index=active_idx)
        if idx is None:
            console.print(info("Cancelled."))
            return None
        return accounts[idx]

    err_con = Console(file=sys.stderr, force_terminal=True, highlight=False)
    err_con.print(card(card_options, title="Select Account"))
    p = str(active or accounts[0].number)
    err_con.print(f"Account [{p}]: ", end="")
    sys.stderr.flush()
    try:
        choice = input()
    except (EOFError, KeyboardInterrupt):
        console.print(info("Cancelled."))
        return None
    choice = choice.strip() or str(active or accounts[0].number)
    acc = find_account(config, choice)
    if acc is None:
        pairs = ", ".join(f"{a.number} ({a.name})" for a in accounts)
        console.print(err(f"Invalid account: {choice}"))
        console.print(f"  Available: {pairs}")
    return acc
