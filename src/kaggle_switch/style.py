"""Terminal styling utilities — zero dependencies, respects NO_COLOR."""
from __future__ import annotations

import os
import sys


def _color_enabled() -> bool:
    if "NO_COLOR" in os.environ:
        return False
    if not sys.stdout.isatty():
        return False
    return True


_ENABLED = _color_enabled()


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
