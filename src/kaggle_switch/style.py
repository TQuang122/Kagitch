"""Terminal styling utilities — uses Rich, respects NO_COLOR."""
from __future__ import annotations

from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Console ────────────────────────────────────────────────────
console = Console(force_terminal=True)

# ── Color theme ─────────────────────────────────────────────────
C_INFO = "cyan"
C_OK = "green"
C_WARN = "yellow"
C_ERROR = "red"
C_ACTIVE = "green"
C_DIM = "bright_black"
C_BORDER = "blue"
C_HEADER = "bold cyan"


def styled(msg: str, style: str) -> str:
    return f"[{style}]{msg}[/]"


def panel_body(title: str, text: str, style: str, subtitle: str = "") -> Panel:
    return Panel(
        text,
        title=title,
        subtitle=subtitle or None,
        border_style=style,
        padding=(1, 2),
    )


def err(msg: str, title: str = "") -> str:
    t = title or "Error"
    return f"[{C_ERROR}]\u2718[/] [{C_ERROR}]{msg}[/]"


def ok(msg: str) -> str:
    return f"[{C_OK}]\u2714[/] [{C_OK}]{msg}[/]"


def warn(msg: str) -> str:
    return f"[{C_WARN}]\u26a0[/] [{C_WARN}]{msg}[/]"


def info(msg: str) -> str:
    return f"[{C_INFO}]\u25b6[/] [{C_INFO}]{msg}[/]"


# ── Rule / separator ────────────────────────────────────────────
def rule() -> None:
    from rich.rule import Rule
    console.print(Rule(style=C_DIM))


# ── Table builder ───────────────────────────────────────────────

def bordered_table(
    headers: list[str],
    rows: Sequence[Sequence[str]],
    *,
    active_index: int | None = None,
    column_options: dict[int, dict] | None = None,
) -> Table:
    """Build a Rich Table renderable with optional active-row highlight
    and alternating row colors.

    *column_options* maps column index to keyword args for add_column(),
    e.g. {0: {"justify": "right", "width": 3}, 2: {"justify": "center"}}.
    """
    table = Table(
        show_header=True,
        show_edge=True,
        padding=(0, 1),
        header_style=C_HEADER,
        border_style=C_BORDER,
    )
    for i, h in enumerate(headers):
        opts = column_options.get(i, {}) if column_options else {}
        table.add_column(h, **opts)
    for i, row in enumerate(rows):
        if i == active_index:
            row_style = f"bold {C_ACTIVE}"
        else:
            row_style = "" if i % 2 == 0 else C_DIM
        strs = [str(c) for c in row]
        table.add_row(*strs, style=row_style)
    return table


# ── Card builder ────────────────────────────────────────────────

def card(lines: list[str], *, title: str = "") -> Panel:
    """Draw a card using Rich Panel."""
    content = "\n".join(lines)
    return Panel.fit(content, title=title, border_style=C_INFO)
