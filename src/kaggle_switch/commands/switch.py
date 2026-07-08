"""Account switching commands."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from rich.console import Console as RichConsole
from rich.prompt import Prompt

from .. import display
from ..config import (
    current_active,
    find_account,
    get_accounts,
    get_token,
)
from ..style import C_OK, card, console, err, info, ok


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


def _apply_account_env(acc) -> None:
    """Apply *acc* credentials to the current process environment in-place."""
    if acc.is_default:
        os.environ.pop("KAGGLE_CONFIG_DIR", None)
    else:
        os.environ["KAGGLE_CONFIG_DIR"] = str(acc.path)

    api_token = get_token(acc)
    if not api_token and acc.auth_type == "oauth":
        api_token = _refresh_oauth_token(acc.path / "credentials.json")
    if api_token:
        os.environ["KAGGLE_API_TOKEN"] = api_token
    else:
        os.environ.pop("KAGGLE_API_TOKEN", None)

    # OAuth: copy credentials.json to ~/.kaggle/ since KAGGLE_CONFIG_DIR
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


def _wrapper_console():
    """Return a stderr-based console in wrapper mode, or the default stdout console."""
    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        return RichConsole(file=sys.stderr, force_terminal=True, highlight=False)
    return console


def cmd_switch(config: dict, key: str) -> int:
    acc = find_account(config, key)
    if acc is None:
        accounts = get_accounts(config)
        out = _wrapper_console()
        if accounts:
            pairs = ", ".join(f"{a.number} ({a.name})" for a in accounts)
            out.print(err(f"Account '{key}' not found"))
            out.print(f"  Available: {pairs}")
        else:
            out.print(err(f"No accounts configured \u2014 use [bold]kagitch add <name>[/]"))
        return 1
    _apply_account_env(acc)

    # Build env lines for shell wrapper mode (printed to stdout for eval)
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

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        for line in env_lines:
            print(line)

    am = display._auth_method(acc.path)
    am_display = display._render_auth(am)
    username = _active_username_from_account(acc)

    if username:
        from .kernel import _auto_patch_metadata

        patch_line = _auto_patch_metadata(Path.cwd(), username)
    else:
        patch_line = None

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

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        _wrapper_console().print(card(lines, title=f"#{acc.number} Switched"))
    else:
        console.print(card(lines, title=f"#{acc.number} Switched"))

    return 0


def cmd_switch_prompt(config: dict) -> int:
    accounts = get_accounts(config)
    if not accounts:
        _wrapper_console().print(err("No accounts configured \u2014 use [bold]kagitch add <name>[/]"))
        return 1

    active = current_active(config)

    rows: list[str] = []
    for acc in accounts:
        badge = display._render_auth(display._auth_method(acc.path))
        marker = " [active]" if acc.number == active else ""
        rows.append(f"  {acc.number}. {acc.name}{marker}  {badge}")

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        err_con = _wrapper_console()
        err_con.print(card(rows, title="Kagitch Accounts"))
        p = str(active or accounts[0].number)
        err_con.print(f"Select account [{p}]: ", end="")
        sys.stderr.flush()
        try:
            choice = input()
        except (EOFError, KeyboardInterrupt):
            err_con.print()
            err_con.print(info("Cancelled."))
            return 1
        choice = choice.strip() or str(active or accounts[0].number)
    else:
        console.print(card(rows, title="Kagitch Accounts"))
        try:
            choice = Prompt.ask("Select account", default=active or accounts[0].number)
        except (KeyboardInterrupt, EOFError):
            console.print()
            console.print(info("Cancelled."))
            return 1

    out = _wrapper_console()
    out.print()
    if find_account(config, choice) is None:
        pairs = ", ".join(f"{a.number} ({a.name})" for a in accounts)
        out.print(err(f"Invalid account: {choice}"))
        out.print(f"  Available: {pairs}")
        return 1
    return cmd_switch(config, choice)


# Import needed by _active_username_from_account
from ..config import get_token as _get_token  # noqa: E402


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





