"""Fetch and render Kaggle kernel logs with Rich formatting."""
from __future__ import annotations

import concurrent.futures
import re
import subprocess  # noqa: S404 — fallback when kaggle SDK unavailable
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .style import console as style_console

# Regex patterns
# _TQDM_RE matches e.g. "  45%|██████ | 23/508 [00:45<01:30,  2.14it/s]"
# _DOWNLOAD_RE matches e.g. "âââ 44.8/44.8 kB eta 0:00:00" (garbled Unicode progress)
_TQDM_RE = re.compile(r"\d+%\|\s*[^|]*\|\s*\d+/\d+\s*\[")
_DOWNLOAD_RE = re.compile(
    r"[\x80-\xFF]{3,}\s*\d+\.?\d*/\d+\.?\d*\s*[kM]B.*eta"
)
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# ── Data model ─────────────────────────────────────────────────

# Matches output like: owner/slug has status "KernelWorkerStatus.COMPLETE"
_KERNEL_STATUS_RE = re.compile(r'has status "KernelWorkerStatus\.(\w+)"')


@dataclass
class LogEntry:
    """Single log line from kaggle kernel output."""
    stream: str        # "stdout" or "stderr"
    timestamp: float   # epoch seconds (0 when not available)
    data: str          # the actual log text


@dataclass
class LogFetchResult:
    """Result of a kaggle kernels logs fetch call."""
    entries: list[LogEntry] = field(default_factory=list)
    status: str = ""         # kernel status string (best-effort)
    error: str = ""          # error message if kaggle failed


# ── Kernel list (for browse mode) ─────────────────────────────


@dataclass
class KernelInfo:
    """Summary info for a single kernel from list output."""
    ref: str          # "owner/slug"
    title: str
    status: str       # "running", "complete", "error", etc.
    last_run_time: str


def get_kernel_status(ref: str) -> str:
    """Fetch status for a single kernel via ``kaggle kernels status <ref>``.

    Returns one of: COMPLETE, RUNNING, QUEUED, ERROR, PENDING, or empty
    string on failure.
    """
    try:
        proc = subprocess.run(
            ["kaggle", "kernels", "status", ref],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    m = _KERNEL_STATUS_RE.search(proc.stdout)
    return m.group(1) if m else ""


def list_kernels(owner: str) -> list[KernelInfo]:
    """List kernels for *owner* via ``kaggle kernels list`` JSON output.

    Returns a list of KernelInfo sorted by last run time (newest first),
    with live status fetched in parallel from ``kaggle kernels status``.
    Returns an empty list on any error.  Skips private kernels (empty ref).
    """
    import json as _json

    try:
        proc = subprocess.run(
            ["kaggle", "kernels", "list", "--user", owner, "--format", "json", "--page-size", "100"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if proc.returncode != 0:
        return []

    stdout = proc.stdout.strip()
    if not stdout:
        return []

    try:
        data = _json.loads(stdout)
    except _json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    results: list[KernelInfo] = []
    for entry in data:
        ref = (entry.get("ref") or "").strip()
        if not ref:
            # Skip private kernels (ref is empty)
            continue
        title = (entry.get("title") or "").strip()
        last_run = (entry.get("lastRunTime") or "").strip()
        results.append(KernelInfo(ref=ref, title=title, status="", last_run_time=last_run))

    # Fetch live statuses in parallel
    refs = [k.ref for k in results]
    status_map: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        future_map = {pool.submit(get_kernel_status, ref): ref for ref in refs}
        for future in concurrent.futures.as_completed(future_map):
            ref = future_map[future]
            try:
                s = future.result()
            except Exception:
                s = ""
            if s:
                status_map[ref] = s

    for k in results:
        k.status = status_map.get(k.ref, "")

    # Sort: newest lastRunTime first (those without a time go last)
    def _sort_key(ki: KernelInfo) -> str:
        return ki.last_run_time or ""

    results.sort(key=_sort_key, reverse=True)
    return results


# ── Fetch ──────────────────────────────────────────────────────


def _try_kaggle_api() -> object | None:
    """Return authenticated KaggleApi or None if the SDK is missing."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        return api
    except Exception:
        return None


def _parse_stream_events(events: list[dict]) -> LogFetchResult:
    """Convert structured SSE events into a LogFetchResult."""
    result = LogFetchResult()
    for ev in events:
        data: str = ev.get("data", "") or ""
        stream = ev.get("stream_name", "stdout")
        timestamp = float(ev.get("time", 0))
        for line in data.rstrip("\n").split("\n"):
            if line:
                result.entries.append(LogEntry(
                    stream=stream, timestamp=timestamp, data=line,
                ))
    return result


def _stream_events(
    kernel: str,
    api: object,
    *,
    max_duration: float = 0,
) -> list[dict]:
    """Collect structured SSE events from ``kernels_logs_stream``.

    When *max_duration* > 0 the collection is bounded by a daemon
    thread timeout; otherwise it streams until the kernel finishes.
    """
    events: list[dict] = []
    exc_info: list[Exception] = []

    def _collect() -> None:
        try:
            for event in api.kernels_logs_stream(kernel):  # type: ignore
                events.append(event)
        except Exception as e:
            exc_info.append(e)

    thread = threading.Thread(target=_collect, daemon=True)
    thread.start()
    thread.join(timeout=max_duration if max_duration > 0 else None)

    if exc_info and not events:
        raise exc_info[0]

    return events


def _parse_plain_logs(raw: str) -> LogFetchResult:
    """Parse plain-text output from 'kaggle kernels logs <kernel>'."""
    result = LogFetchResult()
    text = raw.strip()
    if not text:
        return result
    for line in text.split("\n"):
        result.entries.append(LogEntry(stream="stdout", timestamp=0, data=line))
    return result


def fetch_logs(kernel: str) -> LogFetchResult:
    """Fetch logs for *kernel*, using the streaming SSE API when possible.

    Falls back to subprocess (completed kernels only) when the
    ``kaggle`` Python SDK is not available.
    """
    api = _try_kaggle_api()
    if api is not None:
        try:
            events = _stream_events(kernel, api, max_duration=8.0)
            return _parse_stream_events(events)
        except Exception as e:
            return LogFetchResult(error=str(e))

    # Fallback (completed kernels only)
    try:
        proc = subprocess.run(
            ["kaggle", "kernels", "logs", kernel],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return LogFetchResult(
            error="kaggle CLI not found. Install with: pip install kaggle",
        )
    except subprocess.TimeoutExpired:
        return LogFetchResult(error="kaggle kernels logs timed out after 60s")

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip()
        if err:
            return LogFetchResult(error=err)
        return LogFetchResult(error=f"kaggle exited with code {proc.returncode}")

    return _parse_plain_logs(proc.stdout)


def fetch_logs_follow(
    kernel: str,
    *,
    interval: float = 3.0,
    on_status: callable | None = None,
) -> Iterator[list[LogEntry]]:
    """Stream kernel logs live, yielding new entry batches as they arrive.

    Uses the Kaggle Python streaming API (SSE).  Falls back to polling
    subprocess when the Python SDK is unavailable.
    """
    # Forward status for compatibility
    del interval, on_status

    api = _try_kaggle_api()
    if api is not None:
        return _stream_follow(kernel, api)

    # Fallback — poll subprocess (completed kernels only)
    return _poll_follow(kernel)


def _stream_follow(kernel: str, api: object) -> Iterator[list[LogEntry]]:
    """Stream live logs via Kaggle SSE API, yielding event batches."""
    batch: list[dict] = []
    for event in api.kernels_logs_stream(kernel):  # type: ignore
        batch.append(event)
        if len(batch) >= 10:
            yield _parse_stream_events(batch).entries
            batch.clear()
    if batch:
        yield _parse_stream_events(batch).entries


def _poll_follow(kernel: str) -> Iterator[list[LogEntry]]:
    """Fallback: poll ``kaggle kernels logs`` every 3 seconds."""
    seen_count = 0
    stale_polls = 0
    max_stale = 5

    while True:
        try:
            proc = subprocess.run(
                ["kaggle", "kernels", "logs", kernel],
                capture_output=True, text=True, timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            break

        if proc.returncode != 0:
            break

        result = _parse_plain_logs(proc.stdout)
        new = result.entries[seen_count:]
        seen_count = len(result.entries)
        if new:
            stale_polls = 0
            yield new
        else:
            stale_polls += 1
            if stale_polls >= max_stale:
                break

        time.sleep(3.0)


# ── Render ──────────────────────────────────────────────────────


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from *text*."""
    return _ANSI_RE.sub("", text)


def _is_progress_bar(data: str) -> bool:
    """Return True if *data* is an ephemeral progress-bar line (tqdm, git, etc.)."""
    if _TQDM_RE.search(data):
        return True
    if _DOWNLOAD_RE.search(data):
        return True
    return False


def _format_timestamp(epoch: float, start: float | None = None) -> str:
    """Format epoch as +{rel}s relative to *start* (or first-call)."""
    if epoch == 0:
        return " " * 8
    ref = start if start is not None else epoch
    rel = epoch - ref
    if rel < 0:
        rel = 0
    if rel < 100:
        # Omit decimal when it's a whole number
        if rel == int(rel):
            return f"+{rel:5.0f}s"
        return f"+{rel:5.1f}s"
    return f"+{rel:6.0f}s"


# ── Content-aware line classification ──────────────────────────

# Patterns for classification (compiled once)
_ERROR_PATTERNS = re.compile(
    r"(?:traceback|exception|error:|cuda out of memory|killed|killed)", re.IGNORECASE
)
_WARNING_PATTERNS = re.compile(
    r"(?:warning:|userwarning|incompatible|dependency\s*conflict|requires.*but you have)", re.IGNORECASE
)
_METRIC_PATTERNS = re.compile(
    r"(?:epoch\s+\d+|accuracy\s*:|f1-macro|loss\s*=|saving|saved\s+|validating|top-1)", re.IGNORECASE
)
_NOISE_PATTERNS = re.compile(
    r"(?:wandb:|huggingface_hub|check_worker_number_rationality)", re.IGNORECASE
)

# Phase detection — recognises major workflow stages in Kaggle kernel logs
_PHASE_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"(?:setup|initializing|configuring|preparing)", re.IGNORECASE), "Setup", "bold green"),
    (re.compile(r"(?:pip install|installing|collecting|downloading)", re.IGNORECASE), "Dependencies", "bold yellow"),
    (re.compile(r"(?:training|epoch|train |start training|resume training)", re.IGNORECASE), "Training", "bold magenta"),
    (re.compile(r"(?:validating|validation|evaluating|evaluation|val )", re.IGNORECASE), "Validation", "bold cyan"),
    (re.compile(r"(?:inference|predicting|testing|submitting)", re.IGNORECASE), "Inference", "bold blue"),
]


def _detect_phase(data: str) -> tuple[str, str] | None:
    """Return (phase_label, style) if *data* signals a log phase transition, else None."""
    lower = data.strip().lower()
    for pattern, label, style in _PHASE_PATTERNS:
        if bool(pattern.search(lower)):
            return (label, style)
    return None


def _is_ascii_table_line(data: str) -> bool:
    """Return True if *data* looks like part of an ASCII pipe-delimited table."""
    stripped = data.strip()
    if not stripped.startswith("|"):
        return False
    parts = [p for p in stripped.split("|") if p.strip()]
    if len(parts) < 3:
        return False
    return True


def _parse_ascii_table(raw_lines: list[str]) -> Table | None:
    """Parse buffered ASCII table lines into a Rich Table.

    Handles header, separator (|---|---|), and data rows.
    Returns None if parsing fails.
    """
    headers: list[str] | None = None
    rows: list[list[str]] = []

    for line in raw_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.split("|")]
        # Strip leading/trailing empty cells from the outer pipes
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]

        if not cells:
            continue

        # Separator row → skip
        if all(set(c) <= set("- ") for c in cells):
            continue

        if headers is None:
            headers = cells
        else:
            rows.append(cells)

    if not headers or not rows:
        return None

    ncols = len(headers)
    table = Table(*headers, show_header=True, box=None, padding=(0, 1), collapse_padding=True)
    for row in rows:
        # Pad/truncate to match column count
        padded = (row + [""] * ncols)[:ncols]
        table.add_row(*padded)
    return table


def _merge_table_items(
    items: list[tuple[str, str, str, str, str, int] | None],
) -> list[tuple[str, str, str, str, str, int] | list[str] | None]:
    """Post-process items to merge consecutive ASCII table lines into groups."""
    result: list[tuple[str, str, str, str, str, int] | list[str] | None] = []
    buf: list[str] = []

    for item in items:
        if item is None:
            if buf:
                result.append(buf)
                buf = []
            result.append(None)
            continue

        _ts, _icon, data_str, _style, _group, _repeats = item
        if _repeats > 0:
            # Repeated lines aren't table content
            if buf:
                result.append(buf)
                buf = []
            result.append(item)
        elif _is_ascii_table_line(data_str):
            buf.append(data_str)
        else:
            if buf:
                result.append(buf)
                buf = []
            result.append(item)

    if buf:
        result.append(buf)
    return result


def _classify_line(data: str, stream: str) -> tuple[str, str]:
    """Return (icon, style) for a log line based on content, not stream.

    Classification priority (first match wins):
      1. Error   — actual errors (traceback, CUDA OOM, etc.)
      2. Warning — dependency conflicts, UserWarning, etc.
      3. Metric  — training metrics (epoch, accuracy, loss, F1)
      4. Noise   — wandb sync, HF hub, DataLoader warnings
      5. Source  — indented Python source lines from tracebacks
      6. Default — by stream (stderr → info, stdout → normal)
    """
    stripped = data.strip()
    lower = stripped.lower()

    if _ERROR_PATTERNS.search(lower):
        return "✘", "bold red"

    if _WARNING_PATTERNS.search(lower):
        return "⚠", "yellow"

    if _METRIC_PATTERNS.search(lower):
        return "▶", "bold cyan"

    if _NOISE_PATTERNS.search(lower):
        return "·", "bright_black"

    if stream == "stderr" and (stripped.startswith(("return ", "self.", "raise "))):
        return "·", "bright_black"

    if stream == "stderr":
        return "·", "dim"
    return "▶", "default"


def _get_group(icon: str, style: str) -> str:
    if style == "bold red":
        return "error"
    elif style == "yellow":
        return "warning"
    elif style == "bold cyan":
        return "metric"
    else:
        return "info"


def _prepare_items(
    entries: list[LogEntry],
    *,
    base: float,
    show_progress: bool = False,
    errors_only: bool = False,
    summary_view: bool = False,
    no_group: bool = False,
) -> list[tuple[str, str, str, str, str, int] | None]:
    """Pre-process log entries into ordered render items.

    Each item is ``(ts, icon, data, style, group, repeats)``.
    ``None`` marks a visual section break in the output.
    """
    # Phase 1 — classify, assign groups, insert section breaks
    raw: list[tuple[str, str, str, str, str] | None] = []
    prev_group: str | None = None

    for entry in entries:
        if not show_progress and _is_progress_bar(entry.data):
            continue

        data_str = _strip_ansi(entry.data)
        if len(data_str) > 4000:
            data_str = data_str[:4000] + "..."

        icon, style = _classify_line(data_str, entry.stream)
        group = _get_group(icon, style)
        ts = _format_timestamp(entry.timestamp, base)

        # Section break on error ↔ non-error transitions
        if not no_group and prev_group is not None and group != prev_group:
            if group == "error" or prev_group == "error":
                raw.append(None)
        prev_group = group
        raw.append((ts, icon, data_str, style, group))

    # Phase 2 — filter by view mode
    if errors_only:
        raw = [i for i in raw if i is None or i[4] == "error"]
    elif summary_view:
        raw = [i for i in raw if i is None or i[4] in ("error", "warning", "metric")]

    # Phase 3 — collapse consecutive identical lines
    if no_group:
        return [None if i is None else (i[0], i[1], i[2], i[3], i[4], 0) for i in raw]

    collapsed: list[tuple[str, str, str, str, str, int] | None] = []
    for item in raw:
        if item is None:
            collapsed.append(item)
            continue
        elif collapsed and collapsed[-1] is not None:
            prev = collapsed[-1]
            if prev[2] == item[2] and prev[4] == item[4]:
                collapsed[-1] = (
                    prev[0], prev[1], prev[2], prev[3], prev[4], prev[5] + 1,
                )
                continue
        collapsed.append((item[0], item[1], item[2], item[3], item[4], 0))

    return collapsed


def render_logs(
    entries: list[LogEntry],
    *,
    console: Console | None = None,
    start_time: float | None = None,
    show_progress: bool = False,
    errors_only: bool = False,
    summary_view: bool = False,
    no_group: bool = False,
) -> tuple[int, int, int]:
    """Render a list of LogEntry to the console.

    When *show_progress* is False (the default), tqdm and other
    ephemeral progress-bar lines are filtered out.

    When *errors_only* is True, only error-classified lines are shown.

    When *summary_view* is True, only errors, warnings, and metrics
    are shown (verbose noise is hidden).

    When *no_group* is True, section separators and duplicate
    collapsing are disabled.

    Returns (error_count, warning_count, visible_line_count).
    """
    _console = console or style_console
    if not entries:
        return (0, 0, 0)

    base = start_time if start_time is not None else (entries[0].timestamp if entries else 0)
    items = _prepare_items(
        entries,
        base=base,
        show_progress=show_progress,
        errors_only=errors_only,
        summary_view=summary_view,
        no_group=no_group,
    )

    # Merge consecutive ASCII table lines into table groups
    if not no_group:
        items = _merge_table_items(items)

    counts: dict[str, int] = {"error": 0, "warning": 0, "total": 0}
    current_phase: str | None = None

    for item in items:
        if item is None:
            _console.print(Rule(style="bright_black"))
            continue

        # Table group — render as a Rich Table
        if isinstance(item, list):
            table = _parse_ascii_table(item)
            if table is not None:
                _console.print()
                _console.print(table)
                _console.print()
            else:
                for line in item:
                    _console.print(f"  [default]{line}[/]")
            counts["total"] += len(item)
            continue

        ts, icon, data_str, style, group, repeats = item
        counts["total"] += 1
        if group == "error":
            counts["error"] += 1
        elif group == "warning":
            counts["warning"] += 1

        # Phase detection — show styled header when a new major phase starts
        if not no_group:
            phase = _detect_phase(data_str)
            if phase is not None and phase[0] != current_phase:
                phase_label, phase_style = phase
                current_phase = phase_label
                _console.print()
                _console.print(f"  [{phase_style}]\u25b6 {phase_label}[/]")
                _console.print(Rule(style="bright_black"))

        # Truncate very long lines for readability
        display_str = data_str
        if len(display_str) > 260:
            display_str = display_str[:255] + "[dim]...[bright_black](+{})[/][/]".format(len(display_str) - 255)

        # Two-column layout: fixed-width time column | log data column
        time_col = Text(f"{ts}", style="bright_black")
        data_col = Text()
        data_col.append(f"{icon} ", style=style)
        data_col.append(display_str, style=style)

        row = Table.grid(padding=0)
        row.add_column(width=8, justify="right")
        row.add_column(ratio=1)
        row.add_row(time_col, data_col)
        _console.print(row)

        if repeats:
            label = (
                f"  \u2191 repeated {repeats}"
                f" time{'s' if repeats > 1 else ''}"
            )
            _console.print(label, style="bright_black")

    return (counts["error"], counts["warning"], counts["total"])


def _infer_fix_hint(entries: list[LogEntry]) -> str | None:
    """Return a short fix suggestion if a known error pattern is found."""
    texts = [e.data for e in entries]
    full = " ".join(texts).lower()

    hints = {
        ("cuda out of memory", "out of memory"): "Reduce batch size or use a smaller model",
        ("floatingpointerror",): "Check for NaN in loss/activations — try gradient clipping or reduce LR",
        ("cudnn_status_not_initialized",): "Restart kernel — CUDA state was reset mid-run",
        ("no module named", "importerror"): "Add missing pip install to your kernel notebook",
        ("kaggle_secrets", "usersecrets"): "Secrets may be expired — re-add them in Kaggle UI",
        ("kernel died", "kernel unexpectedly"): "Kernel ran out of memory — reduce model size or batch",
        ("interrupted", "timeout"): "CPU/GPU time limit exceeded — optimize runtime",
        ("connection refused", "timeouterror"): "Network issue — check Kaggle status",
    }
    for keywords, hint in hints.items():
        if all(kw in full for kw in keywords):
            return hint
    return None


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-friendly string."""
    if seconds < 1:
        return "<1s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m {secs}s"


def render_result(
    result: LogFetchResult,
    *,
    console: Console | None = None,
    start_time: float | None = None,
    show_progress: bool = False,
    errors_only: bool = False,
    summary_view: bool = False,
    no_group: bool = False,
    kernel_ref: str = "",
) -> str | None:
    """Render a fully fetched log result. Returns fix hint if one applies.

    When *kernel_ref* is provided, a header Panel with kernel name and
    runtime summary is displayed before the log content.
    """
    _console = console or style_console

    if result.error:
        _console.print(f"[red]\u2718 {result.error}[/]")
        return None

    if not result.entries:
        _console.print("[dim]No log output yet.[/]")
        return None

    # ── Header panel ───────────────────────────────────────────
    if kernel_ref:
        header_lines: list[str] = []
        ref_display = kernel_ref
        header_lines.append(f"[bold cyan]{ref_display}[/]")

        # Compute runtime from first/last entry timestamps
        valid_ts = [e.timestamp for e in result.entries if e.timestamp > 0]
        if valid_ts:
            runtime = valid_ts[-1] - valid_ts[0]
            header_lines.append(
                f"[dim]Runtime:[/dim] [white]{_format_duration(runtime)}[/]"
            )

        if result.status:
            status_colors = {
                "COMPLETE": "green", "complete": "green",
                "ERROR": "bold red", "error": "bold red",
                "RUNNING": "yellow", "running": "yellow",
            }
            sc = status_colors.get(result.status, "dim")
            header_lines.append(f"[dim]Status:[/dim] [{sc}]\u25cf {result.status}[/]")

        _console.print()
        _console.print(Panel(
            "\n".join(header_lines),
            border_style="blue",
            padding=(0, 1),
        ))
        _console.print()

    errors, warnings, total = render_logs(
        result.entries, console=_console, start_time=start_time,
        show_progress=show_progress, errors_only=errors_only,
        summary_view=summary_view, no_group=no_group,
    )

    if total > 0:
        # ── Summary panel ──────────────────────────────────────
        summary_parts: list[str] = []
        if errors:
            summary_parts.append(
                f"[red]\u2718 {errors} error{'s' if errors != 1 else ''}[/]"
            )
        if warnings:
            summary_parts.append(
                f"[yellow]\u26a0 {warnings}"
                f" warning{'s' if warnings != 1 else ''}[/]"
            )
        summary_parts.append(f"[dim]{total} line{'s' if total != 1 else ''}[/]")
        _console.print()
        _console.print(Panel(
            "  " + "   ".join(summary_parts),
            border_style="bright_black",
            padding=(0, 1),
        ))

    hint = _infer_fix_hint(result.entries) if result.entries else None
    if hint:
        _console.print()
        _console.print(Panel(
            f"[yellow]\u26a0 [bold]Possible fix:[/bold] {hint}[/]",
            border_style="yellow",
        ))
    return hint


# ── Help / usage ────────────────────────────────────────────────

def render_logs_help() -> None:
    """Print help for 'kagitch kernel logs'."""
    style_console.print("[bold]Usage:[/bold]")
    style_console.print(
        "  [green]kagitch kernel logs <kernel>[/] "
        "[dim][flags][/]",
    )
    style_console.print(
        "  [green]kagitch kernel logs <owner>/<slug>[/] "
        "[dim]View training logs with rich formatting[/]",
    )
    style_console.print()
    style_console.print("[bold]Flags:[/bold]")
    style_console.print(
        "  [cyan]-f, --follow[/]    Stream live logs (like tail -f)",
    )
    style_console.print(
        "  [cyan]-n <N>[/]         Show last N lines only (default: all)",
    )
    style_console.print("  [cyan]--stdout[/]        Show only stdout lines")
    style_console.print("  [cyan]--stderr[/]        Show only stderr lines")
    style_console.print("  [cyan]--show-progress[/] Show progress-bar lines (filtered by default)")
    style_console.print("  [cyan]-e, --errors-only[/] Show only error-classified lines")
    style_console.print("  [cyan]--summary[/]       Show only errors, warnings, and metrics")
    style_console.print("  [cyan]--no-group[/]      Disable section separators and duplicate collapsing")
    style_console.print("  [cyan]-b, --browse[/]    Interactive kernel picker (no <kernel> argument)")
    style_console.print("  [cyan]-h, --help[/]     Show this help")
    style_console.print()
    style_console.print("[bold]Examples:[/bold]")
    style_console.print("  [dim]kagitch kernel logs my-kernel[/]")
    style_console.print("  [dim]kagitch kernel logs owner/my-kernel -f[/]")
    style_console.print("  [dim]kagitch kernel logs --browse[/]")
    style_console.print("  [dim]kagitch kernel logs my-kernel --stderr[/]")
    style_console.print("  [dim]kagitch kernel logs my-kernel --show-progress[/]")
    style_console.print("  [dim]kagitch kernel logs my-kernel --errors-only[/]")
    style_console.print("  [dim]kagitch kernel logs my-kernel --summary[/]")
