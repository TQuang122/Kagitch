"""Kernel-related commands (init, patch, logs)."""
from __future__ import annotations

import json as _json
import os
import sys
from pathlib import Path

from rich.table import Table
from rich.text import Text

from .. import display
from ..config import current_active, find_account, get_accounts, get_token
from ..style import C_DIM, C_ERROR, C_INFO, C_OK, C_WARN, Console, card, console, err, info, ok
from .switch import _apply_account_env, _active_username_from_account, _refresh_oauth_token  # noqa: F401

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

_ACCELERATOR_CHOICES = [
    "None",
    "GPU",
    "NvidiaTeslaT4",
    "NvidiaTeslaP100",
    "Tpu1VmV38",
]

_GPU_ACCELERATORS = {"GPU", "NvidiaTeslaT4", "NvidiaTeslaP100"}


def _kernel_machine_shape(accelerator: str) -> str:
    """Return Kaggle machine_shape value for a selected accelerator."""
    return "" if accelerator in ("", "None", "GPU") else accelerator


def _kernel_enable_gpu(accelerator: str) -> str:
    """Return Kaggle enable_gpu value for a selected accelerator."""
    return str(accelerator in _GPU_ACCELERATORS).lower()


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


def _kernel_qmark() -> str:
    """Short prompt prefix that avoids the default questionary '?'."""
    return "\u276f"  # heavy right-pointing angle ❯


def _kernel_style():
    """questionary.Style matching the kagitch color theme."""
    import questionary
    return questionary.Style([
        ("qmark", "fg:ansicyan"),
        ("question", "bold"),
        ("answer", "fg:ansigreen"),
        ("pointer", "fg:ansicyan bold"),
        ("selected", "noinherit fg:default"),
        ("highlighted", "fg:ansiblack bg:ansigreen"),
        ("instruction", "fg:ansibrightblack"),
        ("text", "fg:default"),
        ("validation", "fg:ansired bold"),
    ])


def _kernel_init_help() -> None:
    """Print focused help for `kagitch kernel init`."""
    console.print("[bold]Usage:[/bold]")
    console.print(
        "  [green]kagitch kernel init[/] "
        "[dim]Create kernel-metadata.json interactively[/]"
    )
    console.print()
    console.print("[bold]What it asks:[/bold]")
    console.print(
        "  [cyan]title[/], [cyan]slug[/], language, kernel type, "
        "code file, visibility, accelerator, internet, and sources"
    )
    console.print()
    console.print("[bold]Examples:[/bold]")
    console.print("  [green]kagitch kernel init[/]")


def _ask_kernel_init_questions(
    questionary,
    qmark: str,
    qst,
    defaults: dict[str, str],
) -> dict | None:
    """Ask kernel metadata prompts one-by-one to avoid questionary.form spacing."""
    answers: dict = {}

    questions = [
        (
            "title",
            questionary.text("Title", default=defaults["title"], qmark=qmark, style=qst),
        ),
        (
            "slug",
            questionary.text("Kernel slug", default=defaults["slug"], qmark=qmark, style=qst),
        ),
        (
            "lang",
            questionary.select(
                "Language",
                qmark=qmark,
                style=qst,
                choices=["python", "r", "rmarkdown"],
                default=defaults["lang"],
            ),
        ),
        (
            "ktype",
            questionary.select(
                "Kernel type",
                qmark=qmark,
                style=qst,
                choices=["script", "notebook"],
                default=defaults["ktype"],
            ),
        ),
        (
            "code_path",
            questionary.text(
                "Code file",
                qmark=qmark,
                style=qst,
                default=defaults["code_path"],
                validate=lambda v: v.strip() != "" or "Code file is required.",
            ),
        ),
        (
            "is_private",
            questionary.confirm("Private kernel?", default=True, qmark=qmark, style=qst),
        ),
        (
            "accelerator",
            questionary.select(
                "Accelerator",
                qmark=qmark,
                style=qst,
                choices=_ACCELERATOR_CHOICES,
                default="None",
            ),
        ),
        (
            "enable_internet",
            questionary.confirm("Enable internet?", default=True, qmark=qmark, style=qst),
        ),
        (
            "dataset_src",
            questionary.text(
                "Dataset sources (comma-separated, blank=none)",
                default="",
                qmark=qmark,
                style=qst,
            ),
        ),
        (
            "comp_src",
            questionary.text(
                "Competition sources (comma-separated, blank=none)",
                default="",
                qmark=qmark,
                style=qst,
            ),
        ),
        (
            "kernel_src",
            questionary.text(
                "Kernel sources (comma-separated, blank=none)",
                default="",
                qmark=qmark,
                style=qst,
            ),
        ),
        (
            "model_src",
            questionary.text(
                "Model sources (comma-separated, blank=none)",
                default="",
                qmark=qmark,
                style=qst,
            ),
        ),
    ]

    for key, question in questions:
        answer = question.ask()
        if answer is None:
            return None
        answers[key] = answer

    return answers


def cmd_kernel_init(config: dict, args: list[str]) -> int:
    """Interactive wizard to create kernel-metadata.json."""
    import questionary

    cwd = Path.cwd()
    target = cwd / "kernel-metadata.json"

    qmark = _kernel_qmark()
    qst = _kernel_style()

    if target.exists():
        overwrite = questionary.confirm(
            f"{target.name} already exists. Overwrite?",
            default=False, qmark=qmark, style=qst,
        ).ask()
        if overwrite is None or not overwrite:
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
        answers = _ask_kernel_init_questions(
            questionary,
            qmark,
            qst,
            {
                "title": auto_title,
                "slug": auto_slug,
                "lang": auto_lang,
                "ktype": auto_ktype,
                "code_path": str(code_file) if code_file else "",
            },
        )
    except (KeyboardInterrupt, EOFError):
        console.print()
        console.print(info("Cancelled."))
        return 1

    if not answers:
        console.print()
        console.print(info("Cancelled."))
        return 1

    if not answers.get("code_path", "").strip():
        console.print(err("Code file is required."))
        return 1

    # ── build metadata ───────────────────────────────────────────
    kernel_id = f"{username}/{answers['slug']}" if username else answers['slug']
    metadata: dict = {
        "id": kernel_id,
        "title": answers["title"],
        "code_file": answers["code_path"],
        "language": answers["lang"],
        "kernel_type": answers["ktype"],
        "is_private": str(answers["is_private"]).lower(),
        "enable_gpu": _kernel_enable_gpu(answers["accelerator"]),
        "enable_internet": str(answers["enable_internet"]).lower(),
        "machine_shape": _kernel_machine_shape(answers["accelerator"]),
        "dataset_sources": [
            s.strip() for s in answers["dataset_src"].split(",") if s.strip()
        ],
        "competition_sources": [
            s.strip() for s in answers["comp_src"].split(",") if s.strip()
        ],
        "kernel_sources": [
            s.strip() for s in answers["kernel_src"].split(",") if s.strip()
        ],
        "model_sources": [
            s.strip() for s in answers["model_src"].split(",") if s.strip()
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
        f"  title:  [bold]{answers['title']}[/]",
        f"  file:   [bold]{answers['code_path']}[/]",
        f"  lang:   [bold]{answers['lang']}[/]  type: [bold]{answers['ktype']}[/]",
        f"  accelerator: [bold]{answers['accelerator']}[/]",
    ], title="kagitch kernel init"))
    return 0


# ── patch ───────────────────────────────────────────────────────


def _auto_patch_metadata(target: Path, username: str) -> str | None:
    """Patch kernel-metadata.json id to new username.

    Returns a Rich-formatted display line if a patch was applied,
    or ``None`` if nothing changed / no file existed.
    """
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


# ── kernel logs ─────────────────────────────────────────────────


def _parse_logs_args(
    rest: list[str],
) -> tuple[list[str], bool, int, str | None, bool, bool, bool, bool, bool]:
    """Parse args for ``kagitch kernel logs``.

    Returns (positional_args, follow, line_limit, stream_filter,
             show_progress, browse, errors_only, summary, no_group).
    """
    follow = False
    browse = False
    line_limit = 0
    stream_filter: str | None = None
    show_progress = False
    errors_only = False
    summary_view = False
    no_group = False
    positional: list[str] = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("-f", "--follow"):
            follow = True
        elif a in ("-b", "--browse"):
            browse = True
        elif a in ("-n",):
            i += 1
            try:
                line_limit = int(rest[i]) if i < len(rest) else 0
            except ValueError:
                line_limit = 0
        elif a == "--stdout":
            stream_filter = "stdout"
        elif a == "--stderr":
            stream_filter = "stderr"
        elif a == "--show-progress":
            show_progress = True
        elif a in ("-e", "--errors-only"):
            errors_only = True
        elif a == "--summary":
            summary_view = True
        elif a == "--no-group":
            no_group = True
        elif a in ("--help", "-h", "help"):
            positional.append("--help")
        else:
            positional.append(a)
        i += 1
    return positional, follow, line_limit, stream_filter, show_progress, browse, errors_only, summary_view, no_group


def _auto_switch_for_kernel(config: dict, kernel_slug: str) -> bool:
    """Temporarily switch to the account that owns *kernel_slug*.

    Returns True when a switch was performed.
    """
    if "/" not in kernel_slug:
        return False

    owner = kernel_slug.split("/")[0]

    acc = find_account(config, owner)
    if acc is None:
        for a in get_accounts(config):
            if _active_username_from_account(a) == owner:
                acc = a
                break

    if acc is None:
        return False

    active_num = current_active(config)
    if active_num == acc.number:
        return False

    _apply_account_env(acc)
    ok(f"Auto-switched to [bold]{acc.name}[/] for [cyan]{kernel_slug}[/]")
    return True


def cmd_kernel_logs(config: dict, rest: list[str]) -> int:
    """Rich-formatted kernel logs viewer."""
    from ..logs_viewer import (
        fetch_logs,
        fetch_logs_follow,
        render_logs,
        render_logs_help,
        render_result,
    )

    positional, follow, line_limit, stream_filter, show_progress, browse, errors_only, summary_view, no_group = _parse_logs_args(rest)

    enter_browse = browse or (not positional and "--help" not in positional)

    if enter_browse:
        return _browse_kernel_logs(config)

    if "--help" in positional:
        render_logs_help()
        return 0

    kernel = positional[0]

    _auto_switch_for_kernel(config, kernel)

    with display._tty_status(f"[bold green]Fetching logs for [cyan]{kernel}[/]..."):
        result = fetch_logs(kernel)

    if result.error:
        console.print(f"[red]\u2718 {result.error}[/]")
        return 1

    if follow:
        if result.entries:
            render_logs(
                result.entries,
                show_progress=show_progress,
                errors_only=errors_only,
                summary_view=summary_view,
                no_group=no_group,
            )
        try:
            for new_batch in fetch_logs_follow(kernel, on_status=lambda r: None):
                if stream_filter:
                    new_batch = [e for e in new_batch if e.stream == stream_filter]
                if new_batch:
                    render_logs(
                        new_batch,
                        show_progress=show_progress,
                        errors_only=errors_only,
                        summary_view=summary_view,
                        no_group=no_group,
                    )
        except KeyboardInterrupt:
            console.print()
            console.print("[dim]\u2718 Interrupted by user[/]")
        return 0

    if stream_filter:
        result.entries = [e for e in result.entries if e.stream == stream_filter]
    if line_limit > 0:
        result.entries = result.entries[-line_limit:]
    render_result(
        result,
        show_progress=show_progress,
        errors_only=errors_only,
        summary_view=summary_view,
        no_group=no_group,
        kernel_ref=kernel,
    )
    return 0


def _browse_kernel_logs(config: dict) -> int:
    """Interactive browse: pick account -> pick kernel -> show logs."""
    from ..logs_viewer import (
        fetch_logs,
        list_kernels,
        render_result,
    )

    acc = display._select_account_interactive(config)
    if acc is None:
        return 1

    console.print()
    _apply_account_env(acc)
    ok(f"Using [bold]{acc.name}[/]")

    with display._tty_status(f"[bold green]Fetching kernels for [cyan]{acc.name}[/]..."):
        kernels = list_kernels(_active_username_from_account(acc))

    if not kernels:
        console.print(err(f"No kernels found for account [bold]{acc.name}[/]"))
        return 1

    _STATUS_STYLES = {
        "COMPLETE": "green",
        "complete": "green",
        "ERROR": "bold red",
        "error": "bold red",
        "RUNNING": "yellow",
        "running": "yellow",
        "QUEUED": "dim",
        "queued": "dim",
        "PENDING": "dim",
        "pending": "dim",
    }

    table = Table(
        title=f"Kernels for [bold]{acc.name}[/]",
        header_style="bold cyan",
        border_style="blue",
    )
    table.add_column("#", style="dim", no_wrap=True)
    table.add_column("Slug", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status", no_wrap=True)
    table.add_column("Last Run", style="dim")
    for i, k in enumerate(kernels, 1):
        status_str = k.status if k.status else "-"
        status_t = Text(status_str, style=_STATUS_STYLES.get(k.status, "dim")) if k.status else Text("-", style="dim")
        table.add_row(str(i), k.ref, k.title or "-", status_t, k.last_run_time)

    if sys.stderr.isatty():
        console.print(table)
    else:
        try:
            with open("/dev/tty", "w") as tty:
                tty_console = Console(file=tty, force_terminal=True)
                tty_console.print(table)
        except OSError:
            console.print(table)

    _ANSI_STATUS_COLORS = {
        "COMPLETE": "32",
        "complete": "32",
        "ERROR": "1;31",
        "error": "1;31",
        "RUNNING": "33",
        "running": "33",
    }
    kernel_options = []
    for i, k in enumerate(kernels):
        ref_label = f"{i+1}. \x1b[36m{k.ref}\x1b[0m"
        if k.status:
            ansi_color = _ANSI_STATUS_COLORS.get(k.status, "90")
            ref_label += f"  \x1b[{ansi_color}m({k.status})\x1b[0m"
        kernel_options.append(ref_label)
    idx = display._terminal_select(kernel_options)
    if idx is None:
        console.print(info("Cancelled."))
        return 1

    kernel = kernels[idx].ref
    console.print()

    with display._tty_status(f"[bold green]Fetching logs for [cyan]{kernel}[/]..."):
        result = fetch_logs(kernel)

    if result.error:
        console.print(f"[red]\u2718 {result.error}[/]")
        return 1

    render_result(result, kernel_ref=kernel)
    return 0
