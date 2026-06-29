"""CLI entry point."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from rich.traceback import Traceback

from . import __version__
from .config import (
    _next_account_number,
    add_account,
    current_active,
    find_account,
    get_accounts,
    get_token,
    load_config,
    remove_account,
    rename_account,
    save_config,
)
from .shell import (
    completions as shell_completions,
    detect_shell,
    eval_line_for_shell,
    known_cmds_marker,
    rc_file_for_shell,
    shellpath,
)
from .style import (
    C_ACTIVE,
    C_DIM,
    C_ERROR,
    C_INFO,
    C_OK,
    C_WARN,
    bordered_table,
    card,
    console,
    err,
    info,
    ok,
    panel_body,
    rule,
    warn,
)


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


def render_help() -> None:
    _render_banner()
    console.print("[bold]Usage:[/bold]")
    console.print(  "  [green]kagitch[/] [cyan]<command>[/] [dim]\\[options]")
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
                ("kagitch --help", "Show this help"),
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



def cmd_list(config: dict) -> int:
    _render_banner()
    active = current_active(config)
    accounts = get_accounts(config)
    if not accounts:
        console.print(panel_body("", warn("No accounts configured. Add one:"), C_WARN))
        console.print(f"  [green]kagitch add <name> /path/to/kaggle.json[/]")
        return 1

    headers = ["#", "Name", "Config Dir", "Status"]
    rows: list[list[str]] = []
    active_idx: int | None = None
    for i, acc in enumerate(accounts):
        status = "\u25ba active" if acc.number == active else ""
        if acc.number == active:
            active_idx = i
        rows.append([str(acc.number), acc.name, str(acc.path), status])

    col_opts = {0: {"justify": "right", "width": 3}}
    console.print(bordered_table(headers, rows, active_index=active_idx, column_options=col_opts))
    return 0


def cmd_dashboard(config: dict) -> int:
    _render_banner()
    active = current_active(config)
    accounts = get_accounts(config)
    if not accounts:
        console.print(panel_body("", warn("No accounts configured. Add one:"), C_WARN))
        console.print(f"  [green]kagitch add <name> /path/to/kaggle.json[/]")
        return 1

    active_acc = find_account(config, str(active)) if active else None
    active_label = f"#{active_acc.number} {active_acc.name}" if active_acc else "default ~/.kaggle"
    console.print(card([f"  Active  [bold]{active_label}[/]", "", "  Run [bold]kagitch switch[/] to choose another account."], title="Dashboard"))

    headers = ["#", "Name", "Auth", "Path", "Status"]
    rows: list[list[str]] = []
    active_idx: int | None = None
    for i, acc in enumerate(accounts):
        if acc.number == active:
            active_idx = i
        auth = _auth_method(acc.path)
        rows.append([
            acc.number,
            acc.name,
            f"[{C_DIM}]No creds[/]" if auth == "No creds" else _render_auth(auth),
            str(acc.path),
            "\u25ba active" if acc.number == active else "",
        ])

    col_opts = {0: {"justify": "right", "width": 3}, 2: {"justify": "center"}}
    console.print(bordered_table(headers, rows, active_index=active_idx, column_options=col_opts))
    return 0


def cmd_current(config: dict) -> int:
    from .checker import check_account

    n = current_active(config)
    if n is None:
        console.print(warn("No account active (using default ~/.kaggle)"))
        return 0

    acc = find_account(config, n)
    if acc is None:
        console.print(err(f"Account {n} not found in config"))
        return 1

    am = _auth_method(acc.path)
    am_display = _render_auth(am)

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        with _tty_status("[bold green]Checking quota..."):
            cr = check_account(acc)
    else:
        with console.status("[bold green]Checking quota...", spinner="dots") as _:
            cr = check_account(acc)

    lines = [
        f"  [bold]{acc.name}[/]  ({am_display})",
        "",
        f"  \u25b6  {acc.path}",
    ]
    if cr.quota_ok:
        gpu = _render_quota(cr.gpu_remaining)
        tpu = _render_quota(cr.tpu_remaining)
        lines.append("")
        lines.append(f"  GPU  {gpu}")
        lines.append(f"  TPU  {tpu}")
    elif cr.quota_error:
        lines.append("")
        lines.append(f"  [{C_ERROR}]\u2717[/]  {cr.quota_error[:60]}")
    console.print(card(lines, title=f"#{acc.number} Active"))
    return 0


def _add_via_oauth(config: dict, name: str) -> int:
    """Run OAuth flow and register the account."""
    for n, acc in config["accounts"].items():
        if acc["name"] == name:
            console.print(err(f"Account '{name}' already exists as #{n}"))
            return 1

    try:
        from kagglesdk.kaggle_client import KaggleClient
        from kagglesdk.kaggle_oauth import KaggleOAuth

        client = KaggleClient()
        oauth = KaggleOAuth(client)
        console.print(f"[{C_INFO}]\u25b6[/] Opening browser for Kaggle OAuth...")
        creds = oauth.authenticate(scopes=["resources.admin:*"])
        username = creds.get_username()
    except ImportError:
        console.print(err("kagglesdk is required for OAuth login"))
        console.print("  Install: [bold]pip install kagglesdk[/]")
        return 1
    except Exception as e:
        console.print(err(f"OAuth login failed: {e}"))
        return 1

    src = Path.home() / ".kaggle" / "credentials.json"
    target_dir = Path.home() / f".kaggle-{name}"
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / "credentials.json"
    shutil.copy2(src, dest)
    if sys.platform != "win32":
        dest.chmod(0o600)

    next_n = _next_account_number(config)
    entry: dict[str, str] = {"name": name, "config_dir": name, "auth_type": "oauth"}
    config["accounts"][next_n] = entry
    save_config(config)

    console.print(ok(f"Logged in as [bold]{username}[/] \u2192 account #{next_n}: [bold]{name}[/]"))
    console.print(f"  Credentials: {dest}")
    return 0


def cmd_switch(config: dict, key: str) -> int:
    acc = find_account(config, key)
    if acc is None:
        accounts = get_accounts(config)
        if accounts:
            pairs = ", ".join(f"{a.number} ({a.name})" for a in accounts)
            console.print(err(f"Account '{key}' not found"))
            console.print(f"  Available: {pairs}")
        else:
            console.print(err(f"No accounts configured — use [bold]kagitch add <name>[/]"))
        return 1
    env_lines = []
    if acc.is_default:
        env_lines.append("unset KAGGLE_CONFIG_DIR")
    else:
        env_lines.append(f'export KAGGLE_CONFIG_DIR="{acc.path}"')

    api_token = get_token(acc)
    if not api_token and acc.auth_type == "oauth":
        api_token = _refresh_oauth_token(acc.path / "credentials.json")
    if api_token:
        env_lines.append(f'export KAGGLE_API_TOKEN="{api_token}"')
    else:
        env_lines.append("unset KAGGLE_API_TOKEN")

    machine_mode = os.environ.get("KAGITCH_SHELL_WRAPPER") == "1"
    if machine_mode:
        for line in env_lines:
            print(line)

    # OAuth accounts: copy credentials.json to ~/.kaggle/ since KAGGLE_CONFIG_DIR
    # does not redirect it.
    creds_dst = Path.home() / ".kaggle" / "credentials.json"
    if acc.auth_type == "oauth":
        creds_src = acc.path / "credentials.json"
        if creds_src.exists():
            creds_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(creds_src, creds_dst)
            if sys.platform != "win32":
                creds_dst.chmod(0o600)
    elif creds_dst.exists():
        creds_dst.unlink()

    am = _auth_method(acc.path)
    am_display = _render_auth(am)
    username = _active_username_from_account(acc)

    patch_line = _auto_patch_metadata(Path.cwd(), username) if username else None

    lines = [
        f"  {am_display}  [bold]{acc.name}[/]",
    ]
    if username:
        lines.append(f"  [dim]{acc.path}[/]  [cyan]{username}[/]")
    else:
        lines.append(f"  [dim]{acc.path}[/]")
    if patch_line:
        lines.append("")
        lines.append(patch_line)

    if machine_mode:
        from rich.console import Console as _TtyConsole
        _TtyConsole(file=sys.stderr, force_terminal=True, highlight=False).print(
            card(lines, title=f"#{acc.number} Switched")
        )
    else:
        console.print(card(lines, title=f"#{acc.number} Switched"))

    return 0


def cmd_switch_prompt(config: dict) -> int:
    accounts = get_accounts(config)
    if not accounts:
        console.print(err("No accounts configured — use [bold]kagitch add <name>[/]"))
        return 1

    active = current_active(config)

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        from rich.console import Console as _TtyConsole
        err_con = _TtyConsole(file=sys.stderr, force_terminal=True, highlight=False)
        err_con.print("[bold]Kagitch Accounts[/]")
        for acc in accounts:
            badge = _render_auth(_auth_method(acc.path))
            marker = " [active]" if acc.number == active else ""
            if marker:
                err_con.print(f"  {acc.number}. {acc.name}  {badge}  [{C_OK}]{marker.strip()}[/]")
            else:
                err_con.print(f"  {acc.number}. {acc.name}  {badge}")
        p = str(active or accounts[0].number)
        err_con.print(f"Select account [{p}]: ", end="")
        sys.stderr.flush()
        try:
            choice = input()
        except (EOFError, KeyboardInterrupt):
            console.print()
            console.print(info("Cancelled."))
            return 1
        choice = choice.strip() or str(active or accounts[0].number)
    else:
        rows: list[str] = []
        for acc in accounts:
            badge = _render_auth(_auth_method(acc.path))
            marker = " [active]" if acc.number == active else ""
            rows.append(f"  {acc.number}. {acc.name}{marker}  {badge}")
        console.print(card(rows, title="Kagitch Accounts"))
        try:
            choice = Prompt.ask("Select account", default=active or accounts[0].number)
        except (KeyboardInterrupt, EOFError):
            console.print()
            console.print(info("Cancelled."))
            return 1

    console.print()
    if find_account(config, choice) is None:
        pairs = ", ".join(f"{a.number} ({a.name})" for a in accounts)
        console.print(err(f"Invalid account: {choice}"))
        console.print(f"  Available: {pairs}")
        return 1
    return cmd_switch(config, choice)


def _refresh_oauth_token(creds_path: Path) -> str | None:
    """Get a fresh OAuth access token from credentials.json.

    The Kaggle CLI authenticate() checks KAGGLE_API_TOKEN before trying
    OAuth credentials. Setting it bypasses a bug in kaggle==2.2.2 where a
    trailing ``-v`` flag causes ``_authenticate_with_legacy_apikey()`` to
    return True without setting credentials, skipping the OAuth flow.
    """
    if not creds_path.exists():
        return None
    try:
        from kagglesdk.kaggle_client import KaggleClient
        from kagglesdk.kaggle_creds import KaggleCredentials

        client = KaggleClient()
        creds = KaggleCredentials.load(client, str(creds_path))
        if creds is None:
            return None
        return creds.get_access_token()
    except Exception:
        return None


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

    Handles both ``_auth_method()`` output (``"Legacy Key"``,
    ``"OAuth"``) and ``CheckResult.auth_method`` (``"LEGACY_API_KEY"``,
    ``"OAUTH"``).
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


def _parse_quota(h: str) -> float | None:
    """Parse '4.13h' → 4.13, return None on failure."""
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


def cmd_doctor(config: dict) -> int:
    from .checker import check_account

    shell = detect_shell()
    rc = rc_file_for_shell(shell)
    kaggle_path = shutil.which("kaggle")
    accounts = get_accounts(config)
    active_num = current_active(config)
    rc_ok = False

    if rc and rc.exists():
        content = rc.read_text()
        rc_ok = "kagitch" in content and "shellpath" in content

    config_dir = Path.home() / ".kaggle"
    creds = config_dir / "credentials.json"
    active_acc = find_account(config, str(active_num)) if active_num else None

    check_results = [
        bool(kaggle_path),
        rc_ok,
        config_dir.is_dir() and os.access(config_dir, os.R_OK),
        not creds.exists() or os.access(creds, os.R_OK),
        active_acc is not None or active_num is None,
    ]
    passed_checks = sum(1 for result in check_results if result)
    total_checks = len(check_results)

    exit_code = 0
    body = Text()
    body.append(f"  Status: {passed_checks}/{total_checks} checks passed\n", style="bold")
    if passed_checks < total_checks:
        body.append("  Needs action: see recommendations below\n", style=C_WARN)
    body.append("\n")

    def _line(icon: str, style: str, label: str, detail: str, detail_style: str = C_DIM) -> None:
        body.append(f"  {icon}  {label:<18}", style=style)
        body.append(detail, style=detail_style)
        body.append("\n")

    # 1 — Kaggle CLI
    if kaggle_path:
        _line("\u2713", C_OK, "Kaggle CLI", kaggle_path)
    else:
        exit_code = 1
        _line("\u2717", C_ERROR, "Kaggle CLI", "not found \u2014 pip install kaggle")

    # 2 — Shell wrapper installed
    if rc_ok:
        _line("\u2713", C_OK, "Shell wrapper", str(rc) if rc else shell)
    else:
        exit_code = 1
        _line("\u2717", C_ERROR, "Shell wrapper", "not installed \u2014 kagitch init")

    # 3 — Config dir accessible
    if config_dir.is_dir() and os.access(config_dir, os.R_OK):
        _line("\u2713", C_OK, "Config dir", str(config_dir))
    elif config_dir.is_dir():
        _line("\u2717", C_ERROR, "Config dir", f"{config_dir} not readable")
    else:
        _line("\u2014", C_DIM, "Config dir", "not created yet (will be on first use)")

    # 4 — OAuth creds path
    if creds.exists():
        if os.access(creds, os.R_OK):
            _line("\u2713", C_OK, "OAuth creds", str(creds))
        else:
            exit_code = 1
            _line("\u2717", C_ERROR, "OAuth creds", f"{creds} not readable")
    else:
        _line("\u2014", C_DIM, "OAuth creds", "none present (created on OAuth login)")

    # 5 — Active account
    if active_acc:
        _line("\u2713", C_OK, "Active account", f"#{active_acc.number} {active_acc.name}")
    else:
        _line("\u2014", C_INFO, "Active account", "using default ~/.kaggle")

    body.append("\n")

    # ── Account summary ───────────────────────────────────────
    if accounts:
        body.append(f"  Accounts ({len(accounts)}):\n", style=C_INFO)
        for acc in accounts:
            is_active = acc.number == active_num
            am = _auth_method(acc.path)
            if is_active:
                body.append("  \u25ba ", style=C_OK)
            else:
                body.append("    ")
            body.append(f"#{acc.number} ", style="bold")
            body.append(acc.name, style=C_INFO if is_active else "")
            body.append("  ")
            if am == "OAuth":
                body.append("\u2713 OAuth", style=C_OK)
            elif am == "Legacy Key":
                body.append("\u26a0 Legacy Key", style=C_WARN)
            elif am == "No creds":
                body.append("No creds", style=C_ERROR)
            else:
                body.append(f"? {am}", style=C_DIM)
            if is_active:
                body.append("  [active]", style=f"bold {C_OK}")
            body.append("\n")
    else:
        body.append("  No accounts configured.\n", style=C_DIM)

    # ── Quota check for active account ────────────────────────
    if kaggle_path and active_acc:
        _machine = os.environ.get("KAGITCH_SHELL_WRAPPER") == "1"
        if _machine:
            with _tty_status("[bold green]Checking quota..."):
                cr = check_account(active_acc)
        else:
            with console.status("[bold green]Checking quota...", spinner="dots") as _:
                cr = check_account(active_acc)
        body.append(f"\n  Quota ({active_acc.name}):\n", style="")
        if cr.quota_ok:
            body.append(Text.from_markup(f"    \u25b6  GPU  {_render_quota(cr.gpu_remaining)}\n"))
            body.append(Text.from_markup(f"    \u25b6  TPU  {_render_quota(cr.tpu_remaining)}\n"))
        elif cr.quota_error:
            body.append(Text.from_markup(f"    [{C_ERROR}]\u2717[/]  {cr.quota_error[:80]}\n"))
        else:
            body.append(f"    \u2014  n/a\n", style=C_DIM)
    elif kaggle_path and not active_acc:
        body.append(Text.from_markup(f"\n  Quota: [dim]no active account[/]\n"))
    body.append("\n")

    # ── Recommendations ───────────────────────────────────────
    recs: list[str] = []
    if not rc_ok:
        recs.append(f"[bold]kagitch init[/]     install shell wrapper")
    else:
        if shell == "powershell":
            reload_cmd = f"[bold]. {rc}[/] or [bold]kagitch init -r[/]"
        else:
            reload_cmd = f"[bold]source {rc}[/] or [bold]kagitch init -r[/]"
        recs.append(f"{reload_cmd}   reload wrapper in current shell")
    if not kaggle_path:
        recs.append(f"[bold]pip install kaggle[/]   install Kaggle CLI")
    recs.append(f"[bold]kagitch check[/]       detailed quota check for all accounts")

    body.append(f"  Recommendations:\n", style="bold")
    for r in recs:
        body.append(Text.from_markup(f"    \u2192  {r}\n"))

    console.print(panel_body("[bold]kagitch doctor[/]", body, C_INFO))
    return exit_code


def cmd_add(config: dict, args: list[str]) -> int:
    if not args:
        API_URL = "https://www.kaggle.com/settings/api"
        console.print(err("Missing account name."))
        console.print()
        console.print("[bold]Usage:[/]")
        console.print(f"  [{C_INFO}]kagitch add <name>[/]  \u2014 OAuth login (opens browser)")
        console.print(f"  [{C_INFO}]kagitch add <name> <kaggle.json>[/]  \u2014 Legacy API key")
        console.print()
        console.print("[bold]Examples:[/]")
        console.print(f"  [{C_DIM}]# OAuth (recommended):[/]")
        console.print(f"     [{C_INFO}]kagitch add myaccount[/]")
        console.print(f"  [{C_DIM}]# Legacy API key from file:[/]")
        console.print(f"     [{C_INFO}]kagitch add work ~/Downloads/kaggle.json[/]")
        console.print()
        console.print("[bold]Get legacy credentials:[/]")
        console.print("  1. Go to " + f"[{C_INFO}]{API_URL}[/]")
        console.print(
            f"  2. Click [bold]\u201cCreate Legacy API Key\u201d[/] from Legacy API Credentials"
        )
        console.print(f"  3. Run: [{C_INFO}]kagitch add <name> /path/to/kaggle.json[/]")
        return 1

    name = args[0]

    for n, acc in config["accounts"].items():
        if acc["name"] == name:
            console.print(err(f"Account '{name}' already exists as #{n}"))
            return 1

    if len(args) >= 2:
        source = args[1]
        try:
            acc = add_account(config, name, source)
            console.print(ok(f"Added account #{acc.number}: {acc.name}  ({acc.path}/)"))
            return 0
        except (ValueError, FileNotFoundError) as e:
            console.print(err(str(e)))
            return 1

    return _add_via_oauth(config, name)


def cmd_remove(config: dict, args: list[str]) -> int:
    if not args:
        console.print(err("Usage: kagitch remove <N|name>"))
        return 1
    try:
        acc = find_account(config, args[0])
        if acc is None:
            raise KeyError(f"Account '{args[0]}' not found")
        if not Confirm.ask(
            f"[{C_WARN}]\u279c[/] Remove account #{acc.number}: [bold]{acc.name}[/]?\n"
            f"  [dim]Credentials at {acc.path} will be deleted.[/]",
            default=False,
        ):
            console.print(f"[{C_DIM}]Cancelled.[/]")
            return 0
        remove_account(config, args[0])
        console.print(ok("Removed."))
        return 0
    except KeyError as e:
        console.print(err(str(e)))
        return 1


def cmd_rename(config: dict, args: list[str]) -> int:
    if len(args) < 2:
        console.print(err("Usage: kagitch rename <N> <new_name>"))
        return 1
    try:
        acc = rename_account(config, args[0], args[1])
        console.print(ok(f"Renamed #{acc.number}: {acc.name}"))
        return 0
    except KeyError as e:
        console.print(err(str(e)))
        return 1


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
                console.print(f"[{C_INFO}]\u25b6[/] Shell integration already exists in {rc}")
                _reload(shell)
                return 0
        console.print(err("No existing shell integration found. Run [bold]kagitch init[/] first."))
        return 1

    # Shell wrapper captures 2>&1 → interactive wizard output would be
    # invisible.  Open /dev/tty directly to bypass the capture.
    if os.environ.get("KAGITCH_SHELL_WRAPPER"):
        try:
            tty = open("/dev/tty", "w")
        except OSError:
            tty = None
        if tty:
            # Ensure every write hits the terminal before reading stdin —
            # Rich prompts don't end with newlines before input.
            class _Flush:
                def __init__(self, f):
                    self.f = f
                def write(self, s):
                    self.f.write(s)
                    self.f.flush()
                def flush(self):
                    self.f.flush()
            tty_con = Console(file=_Flush(tty), force_terminal=True, highlight=False)
            from .init_wizard import run_wizard
            rc = run_wizard(con=tty_con)
            tty.close()
            return rc

    from .init_wizard import run_wizard
    return run_wizard()


def _reload(shell: str) -> None:
    if shell == "powershell":
        ps_profile = rc_file_for_shell("powershell")
        if ps_profile:
            console.print(f"  Run: [bold]. {ps_profile}[/]")
        else:
            console.print("  Restart your PowerShell session.")
        return

    rc = rc_file_for_shell(shell)
    if rc:
        console.print(f"  Run: [bold]source {rc}[/]")
    else:
        console.print("  Restart your shell to activate.")


def cmd_check(config: dict) -> int:
    from .checker import check_all_accounts

    results: list = []

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        with _tty_status("[bold green]Checking accounts..."):
            results = check_all_accounts(config)
    else:
        with console.status("[bold green]Checking accounts...", spinner="dots") as _:
            results = check_all_accounts(config)

    active_num = current_active(config)
    headers = ["#", "Account", "Auth", "GPU", "TPU", "Reset", "Status"]
    rows: list[list[str]] = []
    active_idx: int | None = None
    for r in results:
        ok = r.auth_match and r.file_ok
        auth_cell = _render_auth(r.auth_method, ok=ok)
        if r.quota_ok:
            gpu = _render_quota(r.gpu_remaining)
            tpu = _render_quota(r.tpu_remaining)
        elif r.quota_error:
            # Show a distinct marker when the quota command itself failed
            gpu = f"[{C_ERROR}]err[/]"
            tpu = ""
        else:
            gpu = f"[{C_DIM}]n/a[/]"
            tpu = f"[{C_DIM}]n/a[/]"
        refresh = r.quota_refresh[:10] if r.quota_refresh else ""
        status = "[bold green]\u25ba active[/]" if r.number == active_num else ""
        if r.number == active_num:
            active_idx = len(rows)
        rows.append([r.number, r.name, auth_cell, gpu, tpu, refresh, status])

    if results:
        col_opts = {
            0: {"justify": "right", "width": 3},
            2: {"justify": "center"},
            3: {"justify": "right"},
            4: {"justify": "right"},
            5: {"justify": "center", "width": 12},
            6: {"justify": "center"},
        }
        console.print()
        console.print(bordered_table(headers, rows, active_index=active_idx, column_options=col_opts))

        any_quota_ok = any(r.quota_ok for r in results)
        quota_errors = [r for r in results if r.quota_error]

        active_name = ""
        if active_num:
            active_acc = find_account(config, active_num)
            if active_acc:
                active_name = active_acc.name
        legacy_count = sum(
            1 for r in results
            if r.auth_method.upper().replace(" ", "_").rstrip("_") in ("LEGACY_API_KEY", "LEGACY_KEY", "LEGACY")
        )

        summary_lines = []
        if any_quota_ok:
            best_gpu = max(results, key=lambda r: _parse_quota(r.gpu_remaining) or 0)
            summary_lines.append(
                f"Best GPU quota : [bold green]{best_gpu.name}[/]  {best_gpu.gpu_remaining}"
            )
        if active_name and any_quota_ok:
            active_gpu = next(
                (r.gpu_remaining for r in results if r.name == active_name),
                "",
            )
            summary_lines.append(
                f"Active account : [bold {C_INFO}]{active_name}[/]  {active_gpu}"
            )
        if quota_errors:
            all_errors = {r.quota_error for r in quota_errors}
            for err_msg in all_errors:
                short = err_msg[:80]
                summary_lines.append(
                    f"[{C_ERROR}]\u2717[/] Quota check: [{C_DIM}]{short}[/]"
                )
        if legacy_count:
            summary_lines.append(
                f"[{C_WARN}]\u26a0[/] {legacy_count} account{'s' if legacy_count > 1 else ''} use Legacy Key"
            )
        # Suggest switching if a different account has more GPU quota
        if any_quota_ok and active_name:
            best_gpu = max(results, key=lambda r: _parse_quota(r.gpu_remaining) or 0)
            if best_gpu.name != active_name and best_gpu.quota_ok:
                switch_num = best_gpu.number
                summary_lines.append(
                    f"[{C_INFO}]\u2192[/] Try [bold]kagitch {switch_num}[/] for more GPU quota ({best_gpu.gpu_remaining})"
                )
        console.print()
        console.print(panel_body("Summary", "\n".join(summary_lines), C_OK))
    return 0


def _auto_patch_metadata(target: Path, username: str) -> str | None:
    """Patch kernel-metadata.json id to new username.

    Returns a Rich-formatted display line if a patch was applied,
    or ``None`` if nothing changed / no file existed.
    """
    import json as _json

    if target.is_dir():
        target = target / "kernel-metadata.json"

    if not target.exists():
        return None

    try:
        data = _json.loads(target.read_text())
    except (_json.JSONDecodeError, OSError):
        return None

    old_id: str | None = data.get("id")
    if not old_id or "/" not in old_id:
        return None

    old_user, kernel = old_id.split("/", 1)
    if old_user == username:
        return None

    new_id = f"{username}/{kernel}"
    data["id"] = new_id
    try:
        target.write_text(_json.dumps(data, indent=2) + "\n")
    except OSError:
        return None

    return (
        f"  [dim]\u21b7[/] [bold]{target.name}[/]: "
        f"[red]{old_user}[/] \u2192 [green]{username}[/]"
        f"  /[cyan]{kernel}[/]"
    )


def _active_username(config: dict) -> str | None:
    import json as _json
    from .config import Account

    active_num = current_active(config)
    if active_num:
        acc = find_account(config, str(active_num))
    else:
        acc = None

    if acc is None:
        acc_dir = Path.home() / ".kaggle"
    else:
        acc_dir = acc.path

    creds = acc_dir / "credentials.json"
    if creds.exists():
        try:
            data = _json.loads(creds.read_text())
            return data.get("username")
        except (_json.JSONDecodeError, OSError):
            pass

    kj = acc_dir / "kaggle.json"
    if kj.exists():
        try:
            data = _json.loads(kj.read_text())
            return data.get("username")
        except (_json.JSONDecodeError, OSError):
            pass

    return None


def _active_username_from_account(acc) -> str | None:
    import json as _json

    creds = acc.path / "credentials.json"
    if creds.exists():
        try:
            data = _json.loads(creds.read_text())
            if data.get("username"):
                return data["username"]
        except (_json.JSONDecodeError, OSError):
            pass

    kj = acc.path / "kaggle.json"
    if kj.exists():
        try:
            data = _json.loads(kj.read_text())
            return data.get("username")
        except (_json.JSONDecodeError, OSError):
            pass

    return None


def cmd_patch(config: dict, args: list[str]) -> int:
    target = Path(args[0]) if args else Path.cwd()
    if target.is_dir():
        target = target / "kernel-metadata.json"
    if not target.exists():
        console.print(err(f"[bold]{target.name}[/] not found in {target.parent}"))
        console.print(f"  [dim]Create one with: kaggle kernels init[/]")
        return 1
    username = _active_username(config)
    if not username:
        console.print(err("Cannot determine active Kaggle username"))
        return 1
    patch_line = _auto_patch_metadata(target, username)
    if patch_line is None:
        console.print(err(f"Failed to patch {target.name}"))
        return 1
    console.print(card([
        ok(f"Patched [bold]{target.name}[/]"),
        "",
        patch_line,
    ], title="kagitch patch"))
    return 0


# ── kernel init ─────────────────────────────────────────────────

_LANG_MAP = {
    ".py": "python",
    ".ipynb": "python",
    ".r": "r",
    ".R": "r",
    ".rmd": "rmarkdown",
    ".Rmd": "rmarkdown",
}

_KTYPE_MAP = {
    ".py": "script",
    ".ipynb": "notebook",
    ".r": "script",
    ".R": "script",
    ".rmd": "script",
    ".Rmd": "script",
}


def _detect_code_file(cwd: Path) -> Path | None:
    """Find the first .py / .ipynb / .r / .Rmd file in *cwd*."""
    candidates = sorted(
        p for p in cwd.iterdir()
        if p.is_file() and p.suffix.lower() in {".py", ".ipynb", ".r", ".rmd"}
    )
    for ext in (".ipynb", ".py"):
        for c in candidates:
            if c.suffix.lower() == ext:
                return c
    return candidates[0] if candidates else None


def cmd_kernel_init(config: dict, args: list[str]) -> int:
    """Interactive wizard to create kernel-metadata.json."""
    import json as _json

    cwd = Path.cwd()
    target = cwd / "kernel-metadata.json"

    if target.exists():
        if not Confirm.ask(
            f"[bold]{target.name}[/] already exists. Overwrite?",
            default=False,
        ):
            console.print(info("Aborted."))
            return 0

    # ── auto-detect ──────────────────────────────────────────────
    username = _active_username(config) or ""
    code_file = _detect_code_file(cwd)
    ext = code_file.suffix if code_file else ""
    auto_lang = _LANG_MAP.get(ext, "python")
    auto_ktype = _KTYPE_MAP.get(ext, "script")
    auto_slug = code_file.stem if code_file else "kernel"
    auto_title = auto_slug.replace("_", " ").replace("-", " ").title()

    # ── prompts ──────────────────────────────────────────────────
    try:
        title = Prompt.ask("Title", default=auto_title)
        slug = Prompt.ask("Kernel slug", default=auto_slug)
        lang = Prompt.ask(
            "Language",
            default=auto_lang,
            choices=["python", "r", "rmarkdown"],
        )
        ktype = Prompt.ask(
            "Kernel type",
            default=auto_ktype,
            choices=["script", "notebook"],
        )

        cf_default = str(code_file) if code_file else ""
        code_path = Prompt.ask("Code file", default=cf_default)
        if not code_path:
            console.print(err("Code file is required."))
            return 1

        is_private = Confirm.ask("Private kernel?", default=True)
        enable_gpu = Confirm.ask("Enable GPU?", default=False)
        enable_tpu = Confirm.ask("Enable TPU?", default=False)
        enable_internet = Confirm.ask("Enable internet?", default=True)

        dataset_src = Prompt.ask(
            "Dataset sources (comma-separated, blank=none)", default=""
        )
        comp_src = Prompt.ask(
            "Competition sources (comma-separated, blank=none)", default=""
        )
        kernel_src = Prompt.ask(
            "Kernel sources (comma-separated, blank=none)", default=""
        )
        model_src = Prompt.ask(
            "Model sources (comma-separated, blank=none)", default=""
        )
    except (KeyboardInterrupt, EOFError):
        console.print()
        console.print(info("Cancelled."))
        return 1

    # ── build metadata ───────────────────────────────────────────
    kernel_id = f"{username}/{slug}" if username else slug
    metadata: dict = {
        "id": kernel_id,
        "title": title,
        "code_file": code_path,
        "language": lang,
        "kernel_type": ktype,
        "is_private": str(is_private).lower(),
        "enable_gpu": str(enable_gpu).lower(),
        "enable_tpu": str(enable_tpu).lower(),
        "enable_internet": str(enable_internet).lower(),
        "machine_shape": "",
        "dataset_sources": [
            s.strip() for s in dataset_src.split(",") if s.strip()
        ],
        "competition_sources": [
            s.strip() for s in comp_src.split(",") if s.strip()
        ],
        "kernel_sources": [
            s.strip() for s in kernel_src.split(",") if s.strip()
        ],
        "model_sources": [
            s.strip() for s in model_src.split(",") if s.strip()
        ],
    }

    # ── write ────────────────────────────────────────────────────
    try:
        target.write_text(_json.dumps(metadata, indent=2) + "\n")
    except OSError as e:
        console.print(err(f"Failed to write {target.name}: {e}"))
        return 1

    console.print(card([
        ok(f"Created [bold]{target.name}[/]"),
        "",
        f"  id:     [cyan]{kernel_id}[/]",
        f"  title:  {title}",
        f"  file:   {code_path}",
        f"  lang:   {lang}  type: {ktype}",
        f"  gpu:    {enable_gpu}  tpu:  {enable_tpu}",
    ], title="kagitch kernel init"))
    return 0


def cmd_completions(args: list[str]) -> int:
    """Print shell completion script."""
    shell = args[0] if args else detect_shell()
    try:
        print(shell_completions(shell), end="")
        return 0
    except ValueError as e:
        console.print(err(str(e)))
        return 1


def cmd_list_accounts(config: dict) -> int:
    """Machine-parseable account list for shell completion (number:name)."""
    from .config import get_accounts

    accounts = get_accounts(config)
    for acc in accounts:
        print(f"{acc.number}:{acc.name}")
    return 0


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
    pkg_dir = Path(__file__).resolve().parent  # src/kaggle_switch/
    root = pkg_dir.parent.parent  # project root

    git_dir = root / ".git"
    if not git_dir.is_dir():
        console.print(err("Not a git installation (installed via pip?)."))
        console.print(info("Re-install with:"))
        console.print("  [green]pip install --upgrade git+https://github.com/TQuang122/Kagitch.git[/]")
        return 1

    old_hash, old_subj = _git_head(cwd=root)

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        console.print(f"[bold]Kagitch {__version__} — updating...[/]")
        cp = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True, text=True,
            cwd=root,
        )
    else:
        with console.status(f"[bold]Kagitch {__version__} — pulling latest...[/]") as _:
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
        ok(f"Updated — [bold]{num_new}[/] new commit{'s' if num_new != 1 else ''}"),
        f"  [dim]{old_hash} → {new_hash}[/]",
        "",
    ]
    for c in new_commits.splitlines():
        lines.append(f"  [dim]├─[/] {c}")
    version_badge = f"v{__version__}"
    console.print(card(lines, title=f"Kagitch {version_badge}"))
    return 0


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
        render_help()
        return 0

    if cmd in ("--version", "-v", "version"):
        _render_banner()
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
            return cmd_kernel_init(config, rest[1:])
        console.print(err("Usage: kagitch kernel init"))
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
    render_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
