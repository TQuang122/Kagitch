"""Terminal styling utilities — zero dependencies, respects NO_COLOR."""
from __future__ import annotations

import os
import re
import sys
from typing import Sequence


def _color_enabled() -> bool:
    if "NO_COLOR" in os.environ:
        return False
    if not sys.stdout.isatty():
        return False
    return True


_ENABLED = _color_enabled()


# ── ANSI helpers ──────────────────────────────────────────────

def _s(code: int, text: str) -> str:
    if not _ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return _s(32, text)


def red(text: str) -> str:
    return _s(31, text)


def yellow(text: str) -> str:
    return _s(33, text)


def cyan(text: str) -> str:
    return _s(36, text)


def bold(text: str) -> str:
    return _s(1, text)


def dim(text: str) -> str:
    return _s(2, text)


def bold_green(text: str) -> str:
    return _s(1, _s(32, text))


def bold_red(text: str) -> str:
    return _s(1, _s(31, text))


def bold_cyan(text: str) -> str:
    return _s(1, _s(36, text))


# ── ANSI-aware string utilities ───────────────────────────────

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def visible_len(text: str) -> int:
    """Return the on-screen display width, ignoring ANSI codes."""
    return len(strip_ansi(text))


def pad_to(text: str, width: int) -> str:
    """Pad text with spaces to the given visual width."""
    return text + " " * max(0, width - visible_len(text))


# ── Icon helpers ──────────────────────────────────────────────

def ok(text: str) -> str:
    return green(f"\u2714 {text}")


def fail(text: str) -> str:
    return red(f"\u2718 {text}")


def info(text: str) -> str:
    return cyan(f"\u25b6 {text}")


def warn(text: str) -> str:
    return yellow(f"\u26a0 {text}")


def prompt(text: str) -> str:
    return yellow(f"\u279c {text}")


def dim_text(text: str) -> str:
    return dim(text)


# ── Table builder ─────────────────────────────────────────────

_BOX = dict(
    TL="\u256d",   # ╭
    TM="\u252c",   # ┬
    TR="\u256e",   # ╮
    ML="\u251c",   # ├
    MM="\u253c",   # ┼
    MR="\u2524",   # ┤
    BL="\u2570",   # ╰
    BM="\u2534",   # ┴
    BR="\u256f",   # ╯
    H="\u2500",    # ─
    V="\u2502",    # │
)


def _fmt_border(left: str, mid: str, right: str, widths: list[int],
                color_fn) -> str:
    parts = [left]
    for i, w in enumerate(widths):
        parts.append(color_fn(_BOX["H"] * w))
        if i < len(widths) - 1:
            parts.append(color_fn(mid))
    parts.append(right)
    return "".join(parts)


def bordered_table(
    headers: list[str],
    rows: Sequence[Sequence[str]],
    *,
    header_color=bold_cyan,
    active_color=bold_green,
    active_index: int | None = None,
) -> str:
    """Build a bordered table with rounded corners.

    ╭──┬──╮
    │  │  │  ← header_color
    ├──┼──┤
    │  │  │
    ╰──┴──╯

    active_index: row index (0-based) to highlight with active_color.
    """
    ncols = len(headers)

    # Calculate column widths (with 1-char internal padding each side)
    col_widths: list[int] = []
    for i, h in enumerate(headers):
        data_max = max(
            (visible_len(str(r[i])) if i < len(r) else 0)
            for r in rows
        ) if rows else 0
        col_widths.append(max(visible_len(h), data_max) + 2)

    lines: list[str] = []
    dim_fn = dim if _ENABLED else (lambda x: x)

    # Top border
    lines.append(_fmt_border(
        _BOX["TL"], _BOX["TM"], _BOX["TR"], col_widths,
        lambda x: x if not _ENABLED else header_color(x),
    ))

    # Header row
    cells: list[str] = []
    for h, w in zip(headers, col_widths):
        cells.append(f" {pad_to(h, w - 1)}")
    header_line = _BOX["V"] + _BOX["V"].join(cells) + _BOX["V"]
    lines.append(header_color(header_line) if _ENABLED else header_line)

    # Separator
    lines.append(_fmt_border(
        _BOX["ML"], _BOX["MM"], _BOX["MR"], col_widths, dim_fn,
    ))

    # Data rows
    for ri, row in enumerate(rows):
        cells = []
        for val, w in zip(row, col_widths):
            s = str(val)
            cells.append(f" {pad_to(s, w - 1)}")
        row_line = _BOX["V"] + _BOX["V"].join(cells) + _BOX["V"]
        if ri == active_index and _ENABLED:
            lines.append(active_color(row_line))
        else:
            lines.append(row_line)

    # Bottom border
    lines.append(_fmt_border(
        _BOX["BL"], _BOX["BM"], _BOX["BR"], col_widths,
        lambda x: x if not _ENABLED else header_color(x),
    ))

    return "\n".join(lines)


# ── Card builder ──────────────────────────────────────────────

def card(lines: list[str], *, title: str = "", color=cyan) -> str:
    """Draw a simple card/box around content lines.

    ┌─ title ────────────────────┐
    │  content                   │
    │  content                   │
    └────────────────────────────┘
    """
    inner = [strip_ansi(l) for l in lines]
    max_w = max(visible_len(l) for l in inner + ([title] if title else []))
    box_w = max(max_w + 4, 30)

    out: list[str] = []
    color_fn = color if _ENABLED else (lambda x: x)

    if title:
        title_part = f" {title} "
        sep_len = box_w - visible_len(title_part) - 2
        left_sep = "\u250c" + "\u2500" * (sep_len // 2)
        right_sep = "\u2500" * (sep_len - sep_len // 2) + "\u2510"
        out.append(color_fn(left_sep + title_part + right_sep))
    else:
        out.append(color_fn("\u250c" + "\u2500" * box_w + "\u2510"))

    for l in inner:
        out.append(color_fn(f"\u2502  {pad_to(l, box_w - 2)}\u2502"))

    out.append(color_fn("\u2514" + "\u2500" * box_w + "\u2518"))
    return "\n".join(out)
