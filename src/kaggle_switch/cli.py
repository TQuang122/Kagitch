"""CLI entry point."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from rich.panel import Panel
from rich.prompt import Confirm
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
    load_config,
    remove_account,
    rename_account,
    save_config,
)
from .shell import (
    completions as shell_completions,
    detect_shell,
    eval_line_for_shell,
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


def _parse_hex(hex: str) -> tuple[int, int, int]:
    h = hex.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _gradient_text(text: str, start_hex: str, end_hex: str, bold: bool = False) -> Text:
    sr, sg, sb = _parse_hex(start_hex)
    er, eg, eb = _parse_hex(end_hex)
    n = max(len(text), 1)
    result = Text()
    for i, ch in enumerate(text):
        t = i / (n - 1) if n > 1 else 0
        r = int(sr + (er - sr) * t)
        g = int(sg + (eg - sg) * t)
        b = int(sb + (eb - sb) * t)
        style_str = f"bold color(#{r:02x}{g:02x}{b:02x})" if bold else f"color(#{r:02x}{g:02x}{b:02x})"
        result.append(ch, style=style_str)
    return result


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
            "Account": ("\U0001f4cb", [
                ("kagitch", "List accounts + show current"),
                ("kagitch <N|name>", "Switch to account"),
                ("kagitch list", "List accounts"),
                ("kagitch current", "Show active account"),
            ]),
            "Health": ("\U0001f50d", [
                ("kagitch check", "Check health + quota for all accounts"),
                ("kagitch doctor", "System diagnostics"),
            ]),
        },
        "right": {
            "Management": ("\u2699\ufe0f", [
                ("kagitch add <name> [kaggle.json]", "Register a new account"),
                ("kagitch remove <N|name>", "Remove an account"),
                ("kagitch rename <N> <new_name>", "Rename an account"),
                ("kagitch patch [path]", "Patch kernel-metadata.json id"),
            ]),
            "Shell integration": ("\U0001f527", [
                ("kagitch init [-r]", "Auto-install shell integration"),
                ("kagitch shellpath <shell>", "Print shell function"),
                ("kagitch completions <shell>", "Print shell completion script"),
            ]),
            "Other": ("\u2139\ufe0f", [
                ("kagitch --version", "Show version"),
                ("kagitch --help", "Show this help"),
            ]),
        },
    }

    def _col_blocks(col: dict) -> Panel:
        parts: list[str] = []
        for title, (icon, rows) in col.items():
            parts.append(f"[bold]{icon} {title}[/]")
            parts.append(_cmd_rows(rows))
            parts.append("")
        return Panel(
            "\n".join(parts[:-1]),  # drop trailing blank
            border_style="bright_black",
            padding=(0, 1),
        )

    main = Table.grid(padding=(0, 2))
    main.add_column()
    main.add_column()
    main.add_row(_col_blocks(sections["left"]), _col_blocks(sections["right"]))
    console.print(main)

    console.print()
    console.print("[bold]Options:[/bold]")
    console.print("  [cyan]-r, --reload[/]   Reload shell after init when supported")

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
        status = "\u25cf active" if acc.number == active else ""
        if acc.number == active:
            active_idx = i
        rows.append([str(acc.number), acc.name, str(acc.path), status])

    col_opts = {0: {"justify": "right", "width": 3}}
    console.print(bordered_table(headers, rows, active_index=active_idx, column_options=col_opts))
    return 0


def cmd_current(config: dict) -> int:
    from .checker import check_all_accounts

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

    with console.status("[bold green]Checking quota...", spinner="dots") as _:
        all_results = check_all_accounts(config)
    cur = next((r for r in all_results if r.number == acc.number), None)

    lines = [
        f"  [bold]{acc.name}[/]  ({am_display})",
        "",
        f"  \u25b6  {acc.path}",
    ]
    if cur and cur.quota_ok:
        gpu = _render_quota(cur.gpu_remaining)
        tpu = _render_quota(cur.tpu_remaining)
        lines.append("")
        lines.append(f"  GPU  {gpu}")
        lines.append(f"  TPU  {tpu}")
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
        console.print(err(f"Account '{key}' not found"))
        return 1
    if acc.is_default:
        print("unset KAGGLE_CONFIG_DIR")
    else:
        print(f"export KAGGLE_CONFIG_DIR={acc.path}")
    if acc.api_token:
        print(f"export KAGGLE_API_TOKEN={acc.api_token}")
    else:
        print("unset KAGGLE_API_TOKEN")

    # OAuth accounts: copy credentials.json to ~/.kaggle/ since KAGGLE_CONFIG_DIR
    # does not redirect it.
    if acc.auth_type == "oauth":
        creds_src = acc.path / "credentials.json"
        if creds_src.exists():
            creds_dst = Path.home() / ".kaggle" / "credentials.json"
            creds_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(creds_src, creds_dst)
            if sys.platform != "win32":
                creds_dst.chmod(0o600)

    # Visual card — shell function passes through non-export lines
    am = _auth_method(acc.path)
    am_display = _render_auth(am)
    arrow = "\u25b6"
    lines = [
        f"  [bold]{acc.name}[/]  ({am_display})",
        "",
        f"  [{C_INFO}]{arrow}[/]  {acc.path}",
    ]
    console.print(card(lines, title=f"#{acc.number} Switched"))

    username = _active_username_from_account(acc)
    if username:
        _auto_patch_metadata(Path.cwd(), username)

    return 0


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
    shell = detect_shell()
    rc = rc_file_for_shell(shell)
    rc_ok = False
    if rc and rc.exists():
        content = rc.read_text()
        rc_ok = "kagitch" in content and "shellpath" in content

    kaggle_path = shutil.which("kaggle")
    accounts = get_accounts(config)
    active_num = current_active(config)

    body = Text()

    if rc_ok:
        body.append(f"  \u2713  Shell: ", style=f"{C_OK}")
    else:
        body.append(f"  \u2717  Shell: ", style=f"{C_ERROR}")
    body.append(str(rc) if rc else str(shell), style="bold")
    body.append("\n")

    if kaggle_path:
        body.append(f"  \u2713  Kaggle CLI: ", style=f"{C_OK}")
        body.append(kaggle_path, style=f"{C_DIM}")
    else:
        body.append(f"  \u2717  Kaggle CLI: ", style=f"{C_ERROR}")
        body.append("not found", style=f"{C_DIM}")
    body.append("\n")

    body.append(f"  Config: {len(accounts)} account", style=f"{C_INFO}")
    if len(accounts) != 1:
        body.append("s")
    body.append("\n\n")

    with console.status("[bold green]Checking accounts...", spinner="dots") as _:
        for acc in accounts:
            am = _auth_method(acc.path)
            is_active = acc.number == active_num
            if is_active:
                body.append("  ", style=f"{C_OK}")
                body.append("\u25c0 ", style=f"{C_OK}")
            else:
                body.append("    ")
            body.append(f"#{acc.number}  ", style="bold")
            body.append(acc.name, style=f"{C_INFO}" if is_active else "")
            body.append("  ")

            if am == "OAuth":
                body.append("\u2713 OAuth", style=C_OK)
            elif am == "Legacy Key":
                body.append("\u26a0 Legacy Key", style=C_WARN)
            elif am == "No creds":
                body.append("No creds", style=C_ERROR)
            else:
                body.append(f"? {am}", style=C_DIM)

            body.append("  ")
            if is_active:
                body.append("\u25cf active", style=f"bold {C_OK}")

            body.append("\n")

    active_dir = ""
    if active_num:
        active_acc = find_account(config, str(active_num))
        if active_acc:
            active_dir = str(active_acc.path)
            body.append(f"\n  Active: {active_dir}", style=C_OK)
    if not active_dir:
        active_dir = str(Path.home() / ".kaggle")
        body.append(f"\n  Active: {active_dir}  (default)", style=C_DIM)

    console.print(panel_body("[bold]kagitch doctor[/]", body, C_INFO))
    return 0


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
        acc = remove_account(config, args[0])
        if Confirm.ask(
            f"[{C_WARN}]\u279c[/] Remove account #{acc.number}: [bold]{acc.name}[/]?",
            default=False,
        ):
            console.print(ok("Removed."))
        else:
            console.print(f"[{C_DIM}]Cancelled.[/]")
            config["accounts"][acc.number] = {
                "name": acc.name,
                "config_dir": acc.config_dir,
            }
            save_config(config)
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

    shell = detect_shell()
    rc = rc_file_for_shell(shell)
    if rc is None:
        console.print(err(f"Cannot detect rc file for shell: {shell}"))
        return 1

    eval_line = eval_line_for_shell(shell)

    if rc.exists():
        content = rc.read_text()
        if "kagitch" in content and "shellpath" in content:
            console.print(f"[{C_INFO}]\u25b6[/] Shell integration already exists in {rc}")
            if reload_shell:
                _reload(shell)
                return 0
            if shell == "powershell":
                console.print(f"  Restart your PowerShell session or run: [bold]. {rc}[/]")
            else:
                console.print(f"  Restart your shell or run: [bold]source {rc}[/]")
            return 0

    console.print(f"[{C_INFO}]\u25b6[/] Detected shell: {shell}")
    console.print(f"  Adding shell integration to: {rc}")
    rc.parent.mkdir(parents=True, exist_ok=True)
    with open(rc, "a") as f:
        f.write(f"\n# kagitch shell integration\n{eval_line}\n")
    console.print()
    console.print(ok("Done!"))

    if reload_shell:
        _reload(shell)
    else:
        if shell == "powershell":
            console.print(f"  Restart PowerShell or run: [bold]. {rc}[/]")
        else:
            console.print(f"  Restart your shell or run: [bold]source {rc}[/]")
    return 0


def _reload(shell: str) -> None:
    import os

    if shell == "powershell":
        shell_path = os.environ.get("SHELL", "powershell.exe")
    else:
        shell_path = os.environ.get("SHELL", "")
    if shell_path:
        console.print(f"  Reloading {shell}...")
        os.execv(shell_path, [shell_path, "-l"])
    console.print("  Restart your shell to activate.")


def cmd_check(config: dict) -> int:
    from .checker import check_all_accounts

    results: list = []

    with console.status("[bold green]Checking accounts...", spinner="dots") as _:
        results = check_all_accounts(config)

    active_num = current_active(config)
    headers = ["#", "Account", "Auth", "GPU", "TPU", "Status"]
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
        status = "[bold green]\u25cf active[/]" if r.number == active_num else ""
        if r.number == active_num:
            active_idx = len(rows)
        rows.append([r.number, r.name, auth_cell, gpu, tpu, status])

    if results:
        col_opts = {
            0: {"justify": "right", "width": 3},
            2: {"justify": "center"},
            3: {"justify": "right"},
            4: {"justify": "right"},
            5: {"justify": "center"},
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
        console.print()
        console.print(panel_body("Summary", "\n".join(summary_lines), C_OK))
    return 0


def _auto_patch_metadata(target: Path, username: str) -> bool:
    import json as _json

    if target.is_dir():
        target = target / "kernel-metadata.json"

    if not target.exists():
        return True  # nothing to patch is fine

    try:
        data = _json.loads(target.read_text())
    except (_json.JSONDecodeError, OSError):
        return False

    old_id: str | None = data.get("id")
    if not old_id or "/" not in old_id:
        return True

    old_user, kernel = old_id.split("/", 1)
    if old_user == username:
        return True

    new_id = f"{username}/{kernel}"
    data["id"] = new_id
    try:
        target.write_text(_json.dumps(data, indent=2) + "\n")
    except OSError:
        return False
    console.print(f"  [dim]\u21b7[/] [bold]{target.name}[/]: [red]{old_user}[/] \u2192 [green]{username}[/]  /[cyan]{kernel}[/]")
    return True


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
        return 1
    username = _active_username(config)
    if not username:
        console.print(err("Cannot determine active Kaggle username"))
        return 1
    if not _auto_patch_metadata(target, username):
        console.print(err(f"Failed to patch {target.name}"))
        return 1
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
        return cmd_list(config)

    cmd = args[0]
    rest = args[1:]

    if cmd in ("--help", "-h", "help"):
        render_help()
        return 0

    if cmd in ("--version", "-v"):
        _render_banner()
        return 0

    if cmd in ("list", "ls"):
        return cmd_list(config)

    if cmd in ("current", "cur", "."):
        return cmd_current(config)

    if cmd == "switch":
        if not rest:
            console.print(warn("Usage: kagitch switch <N>"))
            return 1
        return cmd_switch(config, rest[0])

    if cmd in ("add", "login"):
        return cmd_add(config, rest)
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

    if cmd == "patch":
        return cmd_patch(config, rest)

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
