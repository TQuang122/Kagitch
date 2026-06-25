"""Interactive setup wizard for Kagitch.

Invoked via ``kagitch init`` (no args).  Each step is skippable
and failures don't abort the whole flow.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from rich import box

from . import __version__
from .config import (
    CONFIG_DIR,
    KAGGLE_DEFAULT,
    get_accounts,
    load_config,
    save_config,
)
from .checker import check_all_accounts
from .shell import detect_shell, rc_file_for_shell, eval_line_for_shell, shellpath
from .style import (
    C_ACTIVE,
    C_BORDER,
    C_DIM,
    C_ERROR,
    C_HEADER,
    C_INFO,
    C_OK,
    C_WARN,
    bordered_table,
    card,
    err,
    info,
    ok,
    warn,
)
from .checker import check_all_accounts
from .shell import detect_shell, rc_file_for_shell, eval_line_for_shell, shellpath

STEPS = 7


# ── helpers ────────────────────────────────────────────────────────


def _step_header(con: Console, num: int, title: str) -> None:
    con.print()
    con.print(
        Panel(
            f"[bold]Step {num}/{STEPS}: {title}[/bold]",
            border_style=C_INFO,
        )
    )


def _sub(text: str) -> str:
    return f"  [{C_DIM}]{text}[/]"


def _check_kaggle_cli() -> tuple[bool, str]:
    """Check if ``kaggle`` is on PATH and get its path."""
    p = shutil.which("kaggle")
    if p:
        return True, p
    return False, ""


def _scan_filesystem_dirs() -> list[tuple[str, bool]]:
    """Scan ``~/.kaggle*`` directories.

    Returns list of ``(label, has_creds)`` for dirs that are NOT
    already registered in the config.
    """
    home = Path.home()
    existing: list[tuple[str, bool]] = []
    for d in sorted(home.glob(".kaggle*")):
        if not d.is_dir():
            continue
        # skip the default ~/.kaggle — it is never "unregistered"
        if d.name == ".kaggle":
            continue
        has_creds = any(
            (d / name).exists()
            for name in ("kaggle.json", "credentials.json", "access_token")
        )
        existing.append((d.name, has_creds))
    return existing


def _detect_kernel_metadata(cwd: Path | None = None) -> Path | None:
    """Return path to ``kernel-metadata.json`` in *cwd* or its parent."""
    start = cwd or Path.cwd()
    for p in [start, start.parent]:
        km = p / "kernel-metadata.json"
        if km.exists():
            return km
    return None


def _has_shell_integration() -> bool:
    shell = detect_shell()
    rc = rc_file_for_shell(shell)
    if rc is None or not rc.exists():
        return False
    content = rc.read_text()
    return "kagitch" in content and "shellpath" in content


def _render_auth_badge(auth_type: str) -> str:
    if auth_type == "oauth":
        return f"[{C_OK}]OAuth[/]"
    elif auth_type == "token":
        return f"[{C_INFO}]Token[/]"
    else:
        return f"[{C_WARN}]Legacy Key[/]"


# ── step implementations ───────────────────────────────────────────


def _step_system(con: Console) -> bool:
    """Step 1: check Python, kaggle CLI, git."""
    ok_count = 0
    total = 3

    # Python
    py = sys.version_info
    if py >= (3, 8):
        con.print(ok(f"Python {py.major}.{py.minor}.{py.micro}"))
        ok_count += 1
    else:
        con.print(err(f"Python {py.major}.{py.minor}.{py.micro} — need 3.8+"))

    # Kaggle CLI
    found, path = _check_kaggle_cli()
    if found:
        con.print(ok(f"Kaggle CLI ({path})"))
        ok_count += 1
    else:
        con.print(err("Kaggle CLI not found — install: [bold]pip install kaggle[/]"))

    # Git
    git_path = shutil.which("git")
    if git_path:
        con.print(ok(f"Git ({git_path})"))
        ok_count += 1
    else:
        con.print(warn("Git not found — needed for [bold]kagitch update[/]"))

    all_ok = ok_count == total
    if all_ok:
        con.print(_sub("All dependencies satisfied."))
    else:
        con.print(
            warn(f"{total - ok_count} check{'s' if total - ok_count != 1 else ''} "
                  "need attention but the wizard can continue.")
        )
    return True  # never fatal


def _step_account_scan(
    con: Console, config: dict
) -> tuple[list, list[tuple[str, bool]]]:
    """Step 2: show existing accounts + scan filesystem."""
    accounts = get_accounts(config)

    if accounts:
        table = Table(box=box.SIMPLE, border_style=C_BORDER)
        table.add_column("#", style=C_HEADER, justify="right")
        table.add_column("Name")
        table.add_column("Auth")
        for a in accounts:
            badge = _render_auth_badge(a.auth_type)
            table.add_row(a.number, a.name, badge)
        con.print(table)
        con.print(_sub(f"{len(accounts)} account{'s' if len(accounts) > 1 else ''} configured."))
    else:
        con.print(warn("No accounts configured yet."))

    # scan filesystem dirs not in config
    configured_names = {a.name for a in accounts}
    unreg_dirs = _scan_filesystem_dirs()
    unreg_dirs = [(label, has) for label, has in unreg_dirs
                  if label.replace(".kaggle-", "") not in configured_names]

    if unreg_dirs:
        con.print()
        con.print(info("Detected unregistered Kaggle directories:"))
        for label, has_creds in unreg_dirs:
            cred_mark = ok("has credentials") if has_creds else warn("empty")
            con.print(f"  {_sub(f'{label}  {cred_mark}')}")

    return accounts, unreg_dirs


def _step_add_accounts(
    con: Console, config: dict
) -> bool:
    """Step 3: optionally add accounts interactively."""
    if not Confirm.ask(
        "\nWould you like to add a new Kaggle account?",
        default=False,
        console=con,
    ):
        con.print(_sub("Skipped."))
        return False

    while True:
        name = Prompt.ask("  Account name", console=con)
        if not name.strip():
            con.print(err("Name cannot be empty."))
            continue
        # check duplicate
        existing = get_accounts(config)
        if any(a.name == name.strip() for a in existing):
            con.print(err(f"Account '{name}' already exists."))
            continue
        break

    auth_choice = Prompt.ask(
        "  Auth method",
        choices=["oauth", "token", "legacy"],
        default="oauth",
        console=con,
    )

    name = name.strip()

    if auth_choice == "oauth":
        con.print(info("Opening browser for OAuth login..."))
        con.print(_sub("Follow the browser prompts to authenticate."))
        from .cli import _add_via_oauth
        try:
            result = _add_via_oauth(config, name)
            if result:
                con.print(ok(f"Account '{name}' added via OAuth."))
                return True
            else:
                con.print(err("OAuth login did not complete successfully."))
                return False
        except Exception as e:
            con.print(err(f"OAuth failed: {e}"))
            # Provide manual fallback instructions
            con.print(info("Alternative: create credentials manually and run:"))
            con.print(f"  [green]kagitch add {name} /path/to/kaggle.json[/]")
            con.print(_sub("See: https://www.kaggle.com/settings/api"))
            return False

    elif auth_choice == "token":
        token = Prompt.ask(
            "  Paste your access token",
            password=True,
            console=con,
        )
        if not token.strip():
            con.print(err("Token cannot be empty."))
            return False
        from .config import add_account
        add_account(config, name, token.strip(), auth_type="token")
        save_config(config)
        con.print(ok(f"Account '{name}' added with access token."))
        return True

    else:  # legacy
        path_str = Prompt.ask("  Path to kaggle.json", console=con)
        path = Path(path_str).expanduser().resolve()
        if not path.exists():
            con.print(err(f"File not found: {path}"))
            con.print(info("Download from: https://www.kaggle.com/settings/api"))
            return False
        from .config import add_account
        try:
            add_account(config, name, str(path), auth_type="legacy")
            con.print(ok(f"Account '{name}' added with legacy API key."))
            return True
        except (ValueError, FileNotFoundError) as e:
            con.print(err(str(e)))
            return False


def _step_health_check(con: Console, config: dict) -> list:
    """Step 4: health check all accounts."""
    accounts = get_accounts(config)
    if not accounts:
        con.print(warn("No accounts to check."))
        return []

    con.print(info("Running health checks (this may take a moment)..."))
    try:
        results = check_all_accounts(config)
    except Exception as e:
        con.print(err(f"Health check failed: {e}"))
        return []

    headers = ["#", "Account", "Auth", "Files", "GPU", "Status"]
    rows: list[list[str]] = []
    for r in results:
        auth_str = _render_auth_badge(r.auth_method.lower() if r.auth_method else "")
        files_str = ok("ok") if r.file_ok else err("err")
        gpu_str = r.gpu_remaining or (err("err") if r.quota_error else warn("n/a"))
        status_str = ok("ok") if r.auth_match and r.file_ok else ""
        rows.append([
            r.number,
            r.name,
            auth_str,
            files_str,
            gpu_str,
            status_str,
        ])
    con.print(bordered_table(headers, rows))
    con.print(_sub(f"Checked {len(results)} account{'s' if len(results) != 1 else ''}."))
    return results


def _step_shell_integration(con: Console) -> bool:
    """Step 5: install/reload shell integration."""
    if _has_shell_integration():
        con.print(ok("Shell integration already installed."))
        if Confirm.ask(
            "  Reload shell integration?",
            default=True,
            console=con,
        ):
            _reload_shell(con)
        return True

    if not Confirm.ask(
        "\n  Install shell integration?",
        default=True,
        console=con,
    ):
        con.print(_sub("Skipped. Run [bold]kagitch init[/] later to install."))
        return False

    shell = detect_shell()
    rc = rc_file_for_shell(shell)

    if rc is None:
        con.print(err(f"Cannot detect rc file for shell: {shell}"))
        return False

    eval_line = eval_line_for_shell(shell)

    # Check if already present (race with _has_shell_integration check above)
    if rc.exists() and "kagitch" in rc.read_text() and "shellpath" in rc.read_text():
        con.print(ok("Already present in rc file."))
        return True

    con.print(info(f"Detected shell: {shell}"))
    con.print(info(f"Adding to: {rc}"))
    rc.parent.mkdir(parents=True, exist_ok=True)

    with open(rc, "a") as f:
        f.write(f"\n# kagitch shell integration v{__version__}\n{eval_line}\n")

    con.print(ok("Shell integration added."))
    _reload_shell(con)
    return True


def _reload_shell(con: Console) -> None:
    """Print reload instructions matching the current shell."""
    shell = detect_shell()
    if shell == "powershell":
        rc = rc_file_for_shell("powershell")
        if rc:
            con.print(_sub(f"Run: [bold]. {rc}[/]  (or restart PowerShell)"))
        else:
            con.print(_sub("Restart your PowerShell session."))
    else:
        rc = rc_file_for_shell(shell)
        if rc:
            con.print(_sub(f"Run: [bold]source {rc}[/]  (or restart your shell)"))
        else:
            con.print(_sub("Restart your shell."))


def _step_project_setup(con: Console, config: dict) -> bool:
    """Step 6: detect kernel-metadata.json, offer to patch."""
    km = _detect_kernel_metadata()
    if km is None:
        con.print(warn("No kernel-metadata.json found in current directory."))
        return False

    con.print(ok(f"Found: {km}"))

    # Try to determine active username
    from .cli import _active_username
    username = _active_username(config)
    if not username:
        con.print(warn("Could not determine active Kaggle username."))
        con.print(_sub("Use [bold]kagitch patch[/] later when ready."))
        return False

    # Peek at current owner
    import json as _json
    try:
        data = _json.loads(km.read_text())
        old_id = data.get("id", "")
        if "/" in old_id:
            old_user = old_id.split("/", 1)[0]
            if old_user == username:
                con.print(ok(f"Already set to [bold]{username}[/] — no patch needed."))
                return True
            con.print(warn(f"Owner: {old_user}  →  should be {username}"))
    except (_json.JSONDecodeError, OSError):
        con.print(warn("Could not parse kernel-metadata.json."))
        return False

    if Confirm.ask("  Patch kernel-metadata.json?", default=True, console=con):
        from .cli import _auto_patch_metadata
        patch = _auto_patch_metadata(km, username)
        if patch:
            con.print(ok("Patched:"))
            con.print(f"  {patch}")
            return True
        else:
            con.print(err("Failed to patch."))
            return False

    con.print(_sub("Skipped."))
    return False


def _step_summary(
    con: Console,
    accounts_added: bool,
    accounts_checked: list,
    shell_ok: bool,
    project_patched: bool,
) -> None:
    """Step 7: recap."""
    con.print()
    con.print(
        Panel(
            f"[bold green]Setup complete![/bold green]\n\n"
            f"  Accounts configured  : {len(get_accounts(load_config()))}\n"
            f"  Accounts added       : {'yes' if accounts_added else 'no'}\n"
            f"  Accounts checked     : {len(accounts_checked)}\n"
            f"  Shell integration    : {'yes' if shell_ok else 'no'}\n"
            f"  Project patched     : {'yes' if project_patched else 'no'}",
            title="Summary",
            border_style=C_OK,
        )
    )

    tips: list[str] = []
    if not shell_ok:
        tips.append("Run [bold]kagitch init[/] later to install shell integration.")
    tips.append("Run [bold]kagitch check[/] to monitor quota anytime.")
    tips.append("Switch accounts with [bold]kagitch <N|name>[/]")

    con.print()
    con.print("[bold]Next steps:[/bold]")
    for t in tips:
        con.print(f"  {_sub(t)}")
    con.print()


# ── public API ─────────────────────────────────────────────────────


def run_wizard(con: Console | None = None) -> int:
    """Run the interactive setup wizard.  Returns exit code."""
    con = con or Console(file=sys.stderr, force_terminal=True)
    config = load_config()

    accounts_added = False
    accounts_checked: list = []
    shell_ok = False
    project_patched = False

    # ── Welcome ───────────────────────────────────────────────────
    con.print()
    con.print(
        Panel.fit(
            f"[bold]Kagitch v{__version__} — Setup Wizard[/bold]\n"
            "This guided wizard will help you configure Kagitch.\n"
            "Press [bold]Ctrl+C[/bold] at any time to exit safely.",
            border_style=C_OK,
        )
    )

    # ── Step 1: System dependencies ───────────────────────────────
    _step_header(con, 1, "System Dependencies")
    _step_system(con)

    # ── Step 2: Account scan ──────────────────────────────────────
    _step_header(con, 2, "Account Scan")
    accounts, _ = _step_account_scan(con, config)

    # ── Step 3: Add accounts ──────────────────────────────────────
    _step_header(con, 3, "Add Accounts")
    if _step_add_accounts(con, config):
        accounts_added = True
        # reload config
        config = load_config()
        accounts = get_accounts(config)

    # ── Step 4: Health check ──────────────────────────────────────
    _step_header(con, 4, "Health Check")
    accounts_checked = _step_health_check(con, config)

    # ── Step 5: Shell integration ─────────────────────────────────
    _step_header(con, 5, "Shell Integration")
    shell_ok = _step_shell_integration(con)

    # ── Step 6: Project setup ────────────────────────────────────
    _step_header(con, 6, "Project Setup")
    project_patched = _step_project_setup(con, config)

    # ── Step 7: Summary ───────────────────────────────────────────
    _step_header(con, 7, "Summary")
    _step_summary(con, accounts_added, accounts_checked, shell_ok, project_patched)

    return 0
