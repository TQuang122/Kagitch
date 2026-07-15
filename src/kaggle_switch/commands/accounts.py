"""Account CRUD & listing commands."""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.parse
from pathlib import Path

from rich.prompt import Confirm, Prompt

from .. import display
from ..config import (
    _next_account_number,
    add_account,
    current_active,
    find_account,
    get_accounts,
    get_token,
    remove_account,
    rename_account,
    save_config,
)
from ..style import (
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
    warn,
)

_SUCCESS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kagitch - Authenticated</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
    min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:linear-gradient(135deg,#0f0f1a 0%,#1a1a2e 50%,#16213e 100%);
    color:#e0e0e0
  }
  .card{
    background:rgba(255,255,255,.04);backdrop-filter:blur(12px);
    border:1px solid rgba(255,255,255,.08);border-radius:20px;
    padding:48px 56px;text-align:center;
    box-shadow:0 25px 50px -12px rgba(0,0,0,.5);max-width:420px
  }
  .brand{
    display:flex;align-items:center;justify-content:center;gap:8px;
    margin-bottom:24px
  }
  .brand-prompt{
    font-family:'SF Mono','Fira Code','Cascadia Code',monospace;
    font-size:14px;font-weight:500;
    color:rgba(52,211,153,.55)
  }
  .brand-text{
    font-family:'SF Mono','Fira Code','Cascadia Code',monospace;
    font-size:14px;font-weight:700;letter-spacing:2.5px;
    text-transform:uppercase;
    background:linear-gradient(135deg,#34d399,#06b6d4);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    background-clip:text
  }
  .brand-cursor{
    display:inline-block;width:6px;height:13px;
    background:rgba(52,211,153,.6);
    border-radius:1px;animation:blink 1s step-end infinite
  }
  @keyframes blink{50%{opacity:0}}
  .icon-wrap{
    width:56px;height:56px;margin:0 auto 20px;
    background:rgba(52,211,153,.12);border-radius:50%;
    display:flex;align-items:center;justify-content:center
  }
  .icon-wrap svg{width:28px;height:28px}
  h1{font-size:22px;font-weight:600;color:#fff;margin-bottom:8px}
  p{font-size:14px;color:rgba(255,255,255,.45);line-height:1.5}
</style>
</head>
<body>
<div class="card">
  <div class="brand">
    <span class="brand-prompt">$</span>
    <span class="brand-text">Kagitch</span>
    <span class="brand-cursor"></span>
  </div>
  <div class="icon-wrap">
    <svg viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  </div>
  <h1>Authentication Successful</h1>
  <p>This tab will close automatically</p>
</div>
<script>setTimeout(window.close,3e3)</script>
</body>
</html>"""


def _select_auth_method(con=None) -> str | None:
    options = [
        "1. OAuth login",
        "2. Access token",
        "3. Legacy API key",
        "4. Cancel",
    ]
    if not sys.stdin.isatty() and os.name != "nt":
        try:
            choice = Prompt.ask(
                "How do you want to authenticate?",
                choices=["oauth", "token", "legacy", "cancel"],
                default="oauth",
                console=con or console,
            )
        except (EOFError, KeyboardInterrupt):
            return None
        return None if choice == "cancel" else choice

    idx = display._terminal_select(
        options,
        default_index=0,
        title="How do you want to authenticate?",
        footer="↑/↓ move • Enter select • q cancel",
        subtexts=[
            "Open Kaggle in your browser",
            "Paste a KGAT access token",
            "Import a kaggle.json file",
            "Return without creating an account",
        ],
    )
    if idx is None or idx == 3:
        return None
    return ("oauth", "token", "legacy")[idx]


def _patch_oauth_success_page() -> None:
    """Replace kagglesdk's OAuth success page with the branded Kagitch page."""
    try:
        from kagglesdk.kaggle_oauth import KaggleOAuth

        handler_cls = KaggleOAuth.OAuthCallbackHandler
        orig = handler_cls._handle_oauth_callback

        def _patched(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params and "state" in params:
                code = params["code"][0]
                state = params["state"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                if state == self._oauth_state.state:
                    self.wfile.write(_SUCCESS_HTML.encode())
                    self._on_success(code)
                else:
                    self.wfile.write(b"<html><body><h1>Authentication Failed</h1><p>Invalid state.</p></body></html>")
            else:
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Authentication Failed</h1><p>Invalid callback parameters.</p></body></html>")

        if orig.__code__.co_code != _patched.__code__.co_code:
            handler_cls._handle_oauth_callback = _patched
    except Exception:
        pass


def cmd_list(config: dict) -> int:
    display._render_banner()
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
        status = "\u25ba active" if acc.number == active else ""
        if acc.number == active:
            active_idx = i
        rows.append([str(acc.number), acc.name, str(acc.path), status])

    col_opts = {0: {"justify": "right", "width": 3}}
    console.print(bordered_table(headers, rows, active_index=active_idx, column_options=col_opts))
    return 0


def cmd_dashboard(config: dict) -> int:
    display._render_banner()
    active = current_active(config)
    accounts = get_accounts(config)
    if not accounts:
        console.print(panel_body("", warn("No accounts configured. Add one:"), C_WARN))
        console.print(f"  [green]kagitch add <name> /path/to/kaggle.json[/]")
        return 1

    active_acc = find_account(config, str(active)) if active else None
    active_label = f"#{active_acc.number} {active_acc.name}" if active_acc else "default ~/.kaggle"
    console.print(card([f"  Active  [bold]{active_label}[/]", "", "  Run [bold]kagitch switch[/] to choose another account."], title="Dashboard"))

    headers = ["#", "Name", "Auth", "Path", "Status"]
    rows: list[list[str]] = []
    active_idx: int | None = None
    for i, acc in enumerate(accounts):
        if acc.number == active:
            active_idx = i
        auth = display._auth_method(acc.path)
        rows.append([
            acc.number,
            acc.name,
            f"[{C_DIM}]No creds[/]" if auth == "No creds" else display._render_auth(auth),
            str(acc.path),
            "\u25ba active" if acc.number == active else "",
        ])

    col_opts = {0: {"justify": "right", "width": 3}, 2: {"justify": "center"}}
    console.print(bordered_table(headers, rows, active_index=active_idx, column_options=col_opts))
    return 0


def cmd_current(config: dict) -> int:
    from ..checker import check_account

    n = current_active(config)
    if n is None:
        console.print(warn("No account active (using default ~/.kaggle)"))
        return 0

    acc = find_account(config, n)
    if acc is None:
        console.print(err(f"Account {n} not found in config"))
        return 1

    am = display._auth_method(acc.path)
    am_display = display._render_auth(am)

    if os.environ.get("KAGITCH_SHELL_WRAPPER") == "1":
        with display._tty_status("[bold green]Checking quota..."):
            cr = check_account(acc)
    else:
        with console.status("[bold green]Checking quota...", spinner="dots") as _:
            cr = check_account(acc)

    lines = [
        f"  [bold]{acc.name}[/]  ({am_display})",
        "",
        f"  \u25b6  {acc.path}",
    ]
    if cr.quota_ok:
        gpu = display._render_quota(cr.gpu_remaining)
        tpu = display._render_quota(cr.tpu_remaining)
        lines.append("")
        lines.append(f"  GPU  {gpu}")
        lines.append(f"  TPU  {tpu}")
    elif cr.quota_error:
        lines.append("")
        lines.append(f"  [{C_ERROR}]\u2717[/]  {cr.quota_error[:60]}")
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
        _patch_oauth_success_page()
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
    # Inject username so _active_username_from_account() and downstream
    # readers can find it.
    _creds = json.loads(dest.read_text())
    if username:
        _creds["username"] = username
    dest.write_text(json.dumps(_creds, indent=2))
    if sys.platform != "win32":
        dest.chmod(0o600)

    next_n = _next_account_number(config)
    entry: dict[str, str] = {"name": name, "config_dir": name, "auth_type": "oauth"}
    config["accounts"][next_n] = entry
    save_config(config)

    console.print(ok(f"Logged in as [bold]{username}[/] \u2192 account #{next_n}: [bold]{name}[/]"))
    console.print(f"  Credentials: {dest}")
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

    auth_method = _select_auth_method()
    if auth_method is None:
        console.print(info("Cancelled."))
        return 1
    if auth_method == "oauth":
        return _add_via_oauth(config, name)
    if auth_method == "token":
        token = Prompt.ask("Access token", password=True)
        if not token.strip():
            console.print(err("Token cannot be empty."))
            return 1
        acc = add_account(config, name, token.strip(), auth_type="token")
        save_config(config)
        console.print(ok(f"Added account #{acc.number}: {acc.name}  (access token)"))
        return 0

    source = Prompt.ask("Path to kaggle.json")
    try:
        acc = add_account(config, name, source, auth_type="legacy")
        save_config(config)
        console.print(ok(f"Added account #{acc.number}: {acc.name}  (legacy API key)"))
        return 0
    except (ValueError, FileNotFoundError) as e:
        console.print(err(str(e)))
        return 1


def cmd_remove(config: dict, args: list[str]) -> int:
    if not args:
        console.print(err("Usage: kagitch remove <N|name>"))
        return 1
    try:
        acc = find_account(config, args[0])
        if acc is None:
            raise KeyError(f"Account '{args[0]}' not found")
        console.print()
        console.print(card(
            [
                f"Account #{acc.number}: [bold]{acc.name}[/]",
                f"Credentials: [dim]{acc.path}[/]",
            ],
            title="[yellow]Remove account[/]",
        ))
        import sys; sys.stdout.flush()
        if not Confirm.ask("Delete this account?", default=False):
            console.print(f"  [{C_DIM}]Cancelled.[/]")
            return 0
        remove_account(config, args[0])
        console.print()
        console.print(ok(f"Removed account #{acc.number}: [bold]{acc.name}[/]"))
        return 0
    except KeyError as e:
        console.print(err(str(e.args[0] if e.args else e)))
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
        console.print(err(e.args[0] if e.args else e))
        return 1


def cmd_list_accounts(config: dict) -> int:
    """Machine-parseable account list for shell completion (number:name)."""
    accounts = get_accounts(config)
    for acc in accounts:
        print(f"{acc.number}:{acc.name}")
    return 0
