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
from rich.table import Table

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


def render_logs(
    entries: list[LogEntry],
    *,
    console: Console | None = None,
    start_time: float | None = None,
    show_progress: bool = False,
) -> None:
    """Render a list of LogEntry to the console.

    When *show_progress* is False (the default), tqdm and other
    ephemeral progress-bar lines are filtered out.
    """
    _console = console or style_console
    if not entries:
        return

    base = start_time if start_time is not None else (entries[0].timestamp if entries else 0)

    table = Table(
        show_header=False,
        show_edge=False,
        show_lines=False,
        padding=(0, 1),
        box=None,
    )
    table.add_column("time", style="bright_black", width=9, no_wrap=True)
    table.add_column("icon", width=2, no_wrap=True)
    table.add_column("data")

    for entry in entries:
        # Filter ephemeral progress bars
        if not show_progress and _is_progress_bar(entry.data):
            continue

        ts = _format_timestamp(entry.timestamp, base)
        data_str = _strip_ansi(entry.data)

        # Truncate overly long lines
        if len(data_str) > 4000:
            data_str = data_str[:4000] + "..."

        icon, style = _classify_line(data_str, entry.stream)
        table.add_row(ts, icon, data_str, style=style)

    _console.print(table)


def _infer_fix_hint(entries: list[LogEntry]) -> str | None:
    """Return a short fix suggestion if a known error pattern is found."""
    texts = [e.data for e in entries]
    full = " ".join(texts).lower()

    hints = {
        ("cuda out of memory", "out of memory"): "Reduce batch size or use a smaller model",
        ("floatingpointerror",): "Check for NaN in loss/activations \u2014 try gradient clipping or reduce LR",
        ("cudnn_status_not_initialized",): "Restart kernel \u2014 CUDA state was reset mid-run",
        ("no module named", "importerror"): "Add missing pip install to your kernel notebook",
        ("kaggle_secrets", "usersecrets"): "Secrets may be expired \u2014 re-add them in Kaggle UI",
        ("kernel died", "kernel unexpectedly"): "Kernel ran out of memory \u2014 reduce model size or batch",
        ("interrupted", "timeout"): "CPU/GPU time limit exceeded \u2014 optimize runtime",
        ("connection refused", "timeouterror"): "Network issue \u2014 check Kaggle status",
    }
    for keywords, hint in hints.items():
        if all(kw in full for kw in keywords):
            return hint
    return None


def render_result(
    result: LogFetchResult,
    *,
    console: Console | None = None,
    start_time: float | None = None,
    show_progress: bool = False,
) -> str | None:
    """Render a fully fetched log result. Returns fix hint if one applies."""
    _console = console or style_console

    if result.error:
        _console.print(f"[red]\u2718 {result.error}[/]")
        return None

    if not result.entries:
        _console.print("[dim]No log output yet.[/]")
        return None

    render_logs(result.entries, console=_console, start_time=start_time, show_progress=show_progress)

    hint = None
    if result.entries:
        hint = _infer_fix_hint(result.entries)
        if hint:
            from rich.panel import Panel
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
    style_console.print("  [cyan]-b, --browse[/]    Interactive kernel picker (no <kernel> argument)")
    style_console.print("  [cyan]-h, --help[/]     Show this help")
    style_console.print()
    style_console.print("[bold]Examples:[/bold]")
    style_console.print("  [dim]kagitch kernel logs my-kernel[/]")
    style_console.print("  [dim]kagitch kernel logs owner/my-kernel -f[/]")
    style_console.print("  [dim]kagitch kernel logs --browse[/]")
    style_console.print("  [dim]kagitch kernel logs my-kernel --stderr[/]")
    style_console.print("  [dim]kagitch kernel logs my-kernel --show-progress[/]")
