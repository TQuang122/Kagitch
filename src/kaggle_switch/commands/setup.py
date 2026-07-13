"""Setup & utility commands (init, shellpath, completions, update)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console as RichConsole
from rich.panel import Panel

from .. import __version__, display
from ..shell import (
    completions as shell_completions,
    detect_shell,
    rc_file_for_shell,
    shellpath,
)
from ..style import C_DIM, C_ERROR, C_INFO, C_OK, C_WARN, card, console, err, info, ok


def cmd_shellpath(args: list[str]) -> int:
    shell = args[0] if args else detect_shell()
    try:
        print(shellpath(shell), end="")
        return 0
    except ValueError as e:
        console.print(err(str(e)))
        return 1


def cmd_init(args: list[str] | None = None) -> int:
    reload_shell = False
    if args:
        for a in args:
            if a in ("--reload", "-r"):
                reload_shell = True

    if reload_shell:
        shell = detect_shell()
        rc = rc_file_for_shell(shell)
        if rc and rc.exists():
            content = rc.read_text()
            if "kagitch" in content and "shellpath" in content:
                _reload(shell)
                return 0
        console.print(err("No existing shell integration found. Run [bold]kagitch init[/] first."))
        return 1

    # Shell wrapper captures 2>&1 -> interactive wizard output would be
    # invisible.  Open /dev/tty directly to bypass the capture.
    if os.environ.get("KAGITCH_SHELL_WRAPPER"):
        tty = display._open_tty("w")
        if tty:
            # Ensure every write hits the terminal before reading stdin -
            # Rich prompts don't end with newlines before input.
            class _Flush:
                def __init__(self, f):
                    self.f = f
                def write(self, s):
                    self.f.write(s)
                    self.f.flush()
                def flush(self):
                    self.f.flush()
            tty_con = RichConsole(file=_Flush(tty), force_terminal=True, highlight=False)
            from ..init_wizard import run_wizard
            rc = run_wizard(con=tty_con)
            tty.close()
            return rc

    from ..init_wizard import run_wizard
    return run_wizard()


def _reload(shell: str) -> None:
    """Reload shell integration.

    On Unix this exec's a new login shell so the integration takes effect
    immediately.  On Windows it prints the reload command for PowerShell.
    """
    if shell == "powershell":
        ps_profile = rc_file_for_shell("powershell")
        if ps_profile:
            console.print()
            console.print(Panel(
                f"[bold cyan]. {ps_profile}[/]\n\n"
                "Copy & paste the line above into your PowerShell session,\n"
                "or start a new terminal window.",
                title="Reload PowerShell Profile",
                border_style="green",
            ))
        else:
            console.print("[yellow]Restart your PowerShell session to activate.[/]")
        return

    rc = rc_file_for_shell(shell)
    if not rc:
        console.print("[yellow]Restart your shell to activate.[/]")
        return

    # When the shell wrapper redirects stdout/stderr to a temp file,
    # we must redirect them back to /dev/tty before exec -- otherwise
    # the new login shell inherits the temp-file fd and runs non-interactively.
    if os.environ.get("KAGITCH_SHELL_WRAPPER"):
        if os.name == "nt":
            con = console
        else:
            try:
                tty_fd = os.open("/dev/tty", os.O_RDWR)
                os.dup2(tty_fd, 1)
                os.dup2(tty_fd, 2)
                os.close(tty_fd)
                sys.stdout = os.fdopen(1, "w")
                sys.stderr = os.fdopen(2, "w")
                con = RichConsole(file=sys.stdout, force_terminal=True, highlight=False)
            except OSError:
                con = console
    else:
        con = console

    con.print()
    con.print(Panel(
        f"  [bold cyan]source {rc}[/]\n"
        f"  [bold]exec {shell} -l[/]        \u2014 restart with new integration",
        title="\u2705 Shell Integration Ready",
        border_style="green",
    ))
    con.print(f"[green]Starting new {shell} session...[/]")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp(shell, [shell, "-l"])


def cmd_completions(args: list[str]) -> int:
    """Print shell completion script."""
    shell = args[0] if args else detect_shell()
    try:
        print(shell_completions(shell), end="")
        return 0
    except ValueError as e:
        console.print(err(str(e)))
        return 1


def _git_log(*args: str, cwd: Path) -> str:
    cp = subprocess.run(
        ["git", *args],
        capture_output=True, text=True,
        cwd=cwd,
    )
    return cp.stdout.strip()


def _git_head(cwd: Path) -> list[str]:
    """Get [short_hash, subject] of current HEAD, or ['?','?'] on error."""
    out = _git_log("log", "-1", "--oneline", cwd=cwd)
    if not out:
        return ["?", "?"]
    parts = out.split(maxsplit=1)
    return parts if len(parts) == 2 else [parts[0], ""]


def cmd_update() -> int:
    """Pull the latest version from git."""
    pkg_dir = Path(__file__).resolve().parent.parent  # src/kaggle_switch/
    root = pkg_dir.parent.parent  # project root

    git_dir = root / ".git"
    if not git_dir.is_dir():
        console.print(err("Not a git installation."))
        console.print(info("Update via PyPI:"))
        console.print("  [green]pip install --upgrade kagitch[/]")
        return 1

    old_hash, old_subj = _git_head(cwd=root)

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        console.print(f"[bold]Kagitch {__version__} -- updating...[/]")
        cp = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True, text=True,
            cwd=root,
        )
    else:
        with console.status(f"[bold]Kagitch {__version__} -- pulling latest...[/]") as _:
            cp = subprocess.run(
                ["git", "pull", "--ff-only"],
                capture_output=True, text=True,
                cwd=root,
            )

    if cp.returncode != 0:
        console.print(card([
            err(f"[red]Update failed:[/] {cp.stderr.strip()}"),
            info("Try checking your network or git remote."),
        ], title=f"Kagitch v{__version__}"))
        return 1

    if "Already up to date" in cp.stdout:
        console.print(card([
            ok("Already up to date."),
            f"  [dim]{old_hash} {old_subj}[/]",
        ], title=f"Kagitch v{__version__}"))
        return 0

    new_hash, new_subj = _git_head(cwd=root)
    new_commits = _git_log("log", "--oneline", f"{old_hash}..HEAD", cwd=root)
    num_new = len(new_commits.splitlines()) if new_commits else 0

    lines: list[str] = [
        ok(f"Updated \u2014 [bold]{num_new}[/] new commit{'s' if num_new != 1 else ''}"),
        f"  [dim]{old_hash} \u2192 {new_hash}[/]",
        "",
    ]
    for c in new_commits.splitlines():
        lines.append(f"  [dim]\u2514\u2500[/] {c}")
    version_badge = f"v{__version__}"
    console.print(card(lines, title=f"Kagitch {version_badge}"))
    return 0
