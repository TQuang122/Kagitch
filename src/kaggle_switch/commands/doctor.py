"""Diagnostic commands (doctor, check)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from rich.text import Text

from .. import display
from ..config import current_active, find_account, get_accounts
from ..shell import detect_shell, rc_file_for_shell
from ..style import (
    C_DIM,
    C_ERROR,
    C_INFO,
    C_OK,
    C_WARN,
    bordered_table,
    console,
    err,
    info,
    ok,
    panel_body,
)


def cmd_doctor(config: dict) -> int:
    from ..checker import check_account

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
            am = display._auth_method(acc.path)
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
            with display._tty_status("[bold green]Checking quota..."):
                cr = check_account(active_acc)
        else:
            with console.status("[bold green]Checking quota...", spinner="dots") as _:
                cr = check_account(active_acc)
        body.append(f"\n  Quota ({active_acc.name}):\n", style="")
        if cr.quota_ok:
            body.append(Text.from_markup(f"    \u25b6  GPU  {display._render_quota(cr.gpu_remaining)}\n"))
            body.append(Text.from_markup(f"    \u25b6  TPU  {display._render_quota(cr.tpu_remaining)}\n"))
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


def cmd_check(config: dict) -> int:
    from ..checker import check_all_accounts

    results: list = []

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        with display._tty_status("[bold green]Checking accounts..."):
            results = check_all_accounts(config)
    else:
        with console.status("[bold green]Checking accounts...", spinner="dots") as _:
            results = check_all_accounts(config)

    active_num = current_active(config)
    headers = ["#", "Account", "Auth", "GPU", "TPU", "Reset", "Status"]
    rows: list[list[str]] = []
    active_idx: int | None = None
    for r in results:
        ok_flag = r.auth_match and r.file_ok
        auth_cell = display._render_auth(r.auth_method, ok=ok_flag)
        if r.quota_ok:
            gpu = display._render_quota(r.gpu_remaining)
            tpu = display._render_quota(r.tpu_remaining)
        elif r.quota_error:
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
            best_gpu = max(results, key=lambda r: display._parse_quota(r.gpu_remaining) or 0)
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
            best_gpu = max(results, key=lambda r: display._parse_quota(r.gpu_remaining) or 0)
            if best_gpu.name != active_name and best_gpu.quota_ok:
                switch_num = best_gpu.number
                summary_lines.append(
                    f"[{C_INFO}]\u2192[/] Try [bold]kagitch {switch_num}[/] for more GPU quota ({best_gpu.gpu_remaining})"
                )
        console.print()
        console.print(panel_body("Summary", "\n".join(summary_lines), C_OK))
    return 0
