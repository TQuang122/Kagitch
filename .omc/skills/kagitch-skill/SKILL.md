# Kagitch (kaggle-switch) — Skill for AI Agents

Use this skill when working on the Kagitch CLI tool — a multi-account manager for Kaggle. Covers architecture, command dispatch, config system, shell integration, auth flows, testing, and known gotchas.

## Metadata

- **Project**: [kaggle-switch](https://github.com/your-org/kaggle-switch)
- **Version**: 1.5.1
- **Package name**: `kaggle_switch`
- **CLI name**: `kagitch`
- **Python**: >= 3.8
- **Build system**: hatchling
- **Entry point**: `kaggle_switch.cli:main` (defined in `pyproject.toml [project.scripts]`)

## Project Layout

```
kaggle-switch/
├── pyproject.toml             # Dependencies, scripts, pytest config
├── src/
│   └── kaggle_switch/
│       ├── __init__.py        # __version__ = "1.5.1"
│       ├── cli.py             # Entry point — thin sys.argv dispatch (130 lines)
│       ├── config.py          # Account dataclass, JSON CRUD, platform paths (226 lines)
│       ├── checker.py         # Parallel health/quota checks, kagglesdk patch (441 lines)
│       ├── display.py         # Rich rendering — dashboard, help, tables (591 lines)
│       ├── style.py           # Console, colors, table/card helpers (102 lines)
│       ├── keychain.py        # keyring wrapper for OS credential storage (45 lines)
│       ├── shell.py           # Shell wrapper functions, completions, detection (429 lines)
│       ├── init_wizard.py     # 7-step interactive setup wizard (525 lines)
│       ├── logs_viewer.py     # Rich TUI kernel log viewer (863 lines)
│       └── commands/
│           ├── __init__.py    # Re-exports all cmd_* symbols
│           ├── accounts.py    # Account CRUD — add/remove/rename/list/current/dashboard (444 lines)
│           ├── switch.py      # Account switching logic + env manipulation (218 lines)
│           ├── doctor.py      # Doctor & check commands (272 lines)
│           ├── setup.py       # Init, shellpath, completions, update (219 lines)
│           └── kernel.py      # Kernel init, patch, logs (669 lines)
├── tests/
│   ├── test_cli.py            # End-to-end CLI dispatch tests
│   ├── test_config.py         # Config CRUD, token migration, renumbering
│   ├── test_checker.py        # CheckResult, quota checks, SDK patch
│   ├── test_shell.py          # Shell functions, completions, detection
│   ├── test_switch.py         # Switch internals, OAuth refresh
│   ├── test_kernel.py         # Kernel commands
│   ├── test_display.py        # Rendering, quota formatting
│   └── ... (14 test files total)
└── tests/
    └── AGENTS.md              # Test guidelines for agents
```

## Architecture

### Design Principles

1. **No CLI framework** — Pure `sys.argv` parsing with if/elif. No Click/argparse/Typer.
2. **All output via Rich** — Never bare `print()`. Uses `Console(force_terminal=True)`.
3. **`from __future__ import annotations`** — PEP 604 style hints (Python 3.8+ compat).
4. **Account isolation** via `KAGGLE_CONFIG_DIR` env var — each account has `~/.kaggle-<name>/`.
5. **Shell `eval` injection** — Switching accounts prints `export KAGGLE_CONFIG_DIR=...` to stdout; the shell wrapper `eval`s it in the current shell.
6. **Secrets in OS keychain** — `keyring` library for token storage, never in `accounts.json`.

### Entry Point Flow

```
cli.main()
  └─ cli._main()
       ├─ rich.traceback.install(show_locals=True)
       ├─ config = config.load_config()
       ├─ args = sys.argv[1:]
       └─ if/elif dispatch chain → commands/ handlers
```

All command handlers return `int` exit code. The dispatch chain in `cli.py` is a linear if/elif block (lines 57-122). Every command function is imported from `commands/__init__.py`.

### CLI Dispatch Table

| Arguments | Handler | Module | Key Detail |
|---|---|---|---|
| *(none)* | `cmd_dashboard(config)` | `accounts.py` | Shows dashboard with active account |
| `list`/`ls` | `cmd_list(config)` | `accounts.py` | Lists all accounts in a table |
| `current`/`cur`/`.` | `cmd_current(config)` | `accounts.py` | Shows current active account |
| `switch` *(no arg)* | `cmd_switch_prompt(config)` | `switch.py` | Interactive prompt |
| `switch <N\|name>` | `cmd_switch(config, key)` | `switch.py` | Direct switch |
| `<N>` or `<name>` | `cmd_switch(config, cmd)` | `switch.py` | Shorthand — checks if arg is digit or matches account name |
| `add`/`login <name>` | `cmd_add(config, args)` | `accounts.py` | OAuth or legacy key add |
| `remove`/`rm` | `cmd_remove(config, args)` | `accounts.py` | Removes account + credentials |
| `rename <N> <name>` | `cmd_rename(config, args)` | `accounts.py` | Just renames in JSON |
| `check` | `cmd_check(config)` | `doctor.py` | Parallel health + quota check |
| `doctor` | `cmd_doctor(config)` | `doctor.py` | System diagnostics |
| `init` | `cmd_init(args)` | `setup.py` | 7-step interactive wizard |
| `init -r` | `cmd_init(["-r"])` | `setup.py` | Print reload command |
| `shellpath [shell]` | `cmd_shellpath(args)` | `setup.py` | Print eval shell function |
| `completions <sh>` | `cmd_completions(args)` | `setup.py` | Print completion script |
| `update` | `cmd_update()` | `setup.py` | Git pull latest |
| `patch [path]` | `cmd_patch(config, args)` | `kernel.py` | Patch kernel-metadata.json id |
| `kernel init` | `cmd_kernel_init(config, args)` | `kernel.py` | Interactive kernel metadata creation |
| `kernel logs` | `cmd_kernel_logs(config, args)` | `kernel.py` | Fetch/render kernel logs |
| `__list_accounts` | `cmd_list_accounts(config)` | `accounts.py` | Internal — for shell completions |
| *(unknown)* | tries numeric/name → `cmd_switch`, else error + help | `cli.py:121-126` | |

## Key Modules Deep Dive

### `config.py` — Account Dataclass & JSON Persistence

```python
@dataclass
class Account:
    number: str       # "1", "2", "3"... (sequential string)
    name: str         # User-chosen name
    config_dir: str   # Suffix for ~/.kaggle-<suffix>; empty = default ~/.kaggle
    api_token: str = ""    # Cleartext token (cleared by migration to keychain)
    auth_type: str = ""    # "", "oauth", "token"

    @property
    def path(self) -> Path
    @property
    def is_default(self) -> bool
```

**Config location:**
- Linux/macOS: `~/.config/kagitch/accounts.json`
- Windows: `%APPDATA%/kagitch/accounts.json`

**Key functions:**
| Function | What it does |
|---|---|
| `load_config()` | Reads JSON, runs renumber + token migration, saves compaction |
| `save_config(config)` | Renumbers, mkdir, writes JSON |
| `get_accounts(config) -> list[Account]` | Sorted by number |
| `find_account(config, key) -> Account\|None` | By number or name |
| `current_active(config) -> str\|None` | Checks `$KAGGLE_CONFIG_DIR` env var |
| `add_account(config, name, source, auth_type)` | 3 modes: None, token string, file path |
| `remove_account(config, key)` | Deletes config + keychain + filesystem |
| `rename_account(config, key, new_name)` | Renames in JSON only |
| `get_token(account) -> str` | Keychain first, then account.api_token fallback |

**Critical behaviors:**
- `_renumber_accounts()` runs on every load and save — removal of account #2 renumbers #3 → #2.
- `_migrate_plaintext_tokens()` moves tokens from JSON to OS keychain on every `load_config()`.

### `checker.py` — Health Checking & Quota

**Data flow:**
```
check_all_accounts(config)
  └─ ThreadPoolExecutor(max_workers=4) — parallel per account
       └─ check_account(acc) -> CheckResult
            ├─ Phase 0: kaggle CLI on PATH?
            ├─ Phase 1: File check — kaggle.json / access_token / credentials.json exist?
            ├─ Phase 2: Auth check — `kaggle config view` via _run_with_creds()
            └─ Phase 3: Quota check — kagglesdk first, then `kaggle quota` CLI fallback
```

**kagglesdk TimeDeltaSerializer patch** (lines 24-44):
- `kagglesdk <= 0.1.30` crashes on whole-second durations like `"0s"` (no decimal).
- The patch replaces `TimeDeltaSerializer._from_dict_value` with a version that handles single-element splits.
- Applied at module import time. If you add kagglesdk-dependent code, this patch must be loaded first.

**Credential isolation** (`_build_env`, `_run_with_creds`):
- `_build_env()` **strips** `KAGGLE_API_TOKEN` from env to prevent token leakage across accounts. kaggle CLI 2.2+ prioritizes this env var over config files.
- `_run_with_creds()` physically copies `credentials.json` → `~/.kaggle/credentials.json` before running subprocess, then restores backup. Thread-safe via `_creds_lock` (threading.Lock).
- `_patch_creds_expiry()` fixes timezone-naive timestamps by appending `+00:00` — prevents `TypeError: can't compare offset-naive and offset-aware datetimes` in kagglesdk.

### `keychain.py` — OS Keychain Wrapper

```python
SERVICE_NAME = "kagitch"
store_token(account_name, token) -> bool
get_token(account_name) -> Optional[str]
delete_token(account_name) -> bool
```

All three gracefully return `False`/`None` if `keyring` import fails. Uses `KEYRING_AVAILABLE` flag.

### `shell.py` — Shell Integration

**Supported shells:** `zsh`, `bash`, `fish`, `powershell`

**Shell wrapper concept:**
The `kagitch` CLI command is replaced by a shell function that:
1. Captures stdout from `kagitch switch <N>` (contains `export KAGGLE_CONFIG_DIR=...`)
2. `eval`s those lines in the current shell
3. Passes stderr through to the terminal (carries Rich UI)
4. Uses `KAGITCH_SHELL_WRAPPER=1` env var to signal to the Python process

**When `KAGITCH_SHELL_WRAPPER=1` is set:**
- `cmd_switch` prints `export KAGGLE_CONFIG_DIR=...` to stdout instead of Rich tables
- Status displays use `_tty_status("/dev/tty")` because stdout is captured for eval
- `cmd_switch_prompt` reads from `input()` on stderr-based console, not Rich's `Prompt.ask`
- The wrapper bypasses all this for `kernel init` (returns JSON to stdout)

**Shell detection:**
- Checks `$SHELL` env var → zsh/bash/fish/pwsh
- Windows fallback → `powershell`
- Unrecognized → `zsh` (default)

**RC file resolution:**
- zsh: `~/.zshrc`
- bash: `~/.bashrc`
- fish: `~/.config/fish/config.fish`
- powershell: `$PROFILE` (PS7 then PS5.1)

### `style.py` and `display.py` — Terminal UI

**Color theme** from `style.py`:

| Constant | Color | Usage |
|---|---|---|
| `C_INFO` | cyan | Informational |
| `C_OK` | green | Success |
| `C_WARN` | yellow | Warnings |
| `C_ERROR` | red | Errors |
| `C_ACTIVE` | green | Active account |
| `C_DIM` | bright_black | Secondary text |
| `C_BORDER` | blue | Table borders |
| `C_HEADER` | bold cyan | Table headers |

**Key helpers:**
- `styled(msg, style)` → Rich markup string
- `err/ok/warn/info(msg)` → color-prefixed strings
- `bordered_table(headers, rows, *, active_index, column_options)` → Table with active-row highlighting
- `card(lines, *, title="")` → Panel wrapper
- `panel_body(title, text, style)` → Rich Panel
- `_terminal_select(options, ...)` → cross-platform terminal picker (Unix termios / Windows msvcrt)

### `commands/switch.py` — Account Switching

The most critical flow in the entire codebase:

```
cmd_switch(config, key)
  ├─ account = find_account(config, key)
  ├─ _apply_account_env(account)
  │    ├─ Sets os.environ["KAGGLE_CONFIG_DIR"] = str(account.path)
  │    └─ Sets os.environ["KAGGLE_API_TOKEN"] = config.get_token(account)
  ├─ For OAuth accounts:
  │    ├─ _refresh_oauth_token(account) — HTTP POST refresh_token → get new access_token
  │    └─ Copies credentials.json → ~/.kaggle/credentials.json
  ├─ Prints "export KAGGLE_CONFIG_DIR=..." + "export KAGGLE_API_TOKEN=..." via console.print()
  └─ Returns 0
```

**OAuth credential copy on switch** (lines 60-71 of switch.py):
When switching to an OAuth account, `credentials.json` is physically copied from `~/.kaggle-{name}/` to `~/.kaggle/` because `kaggle` CLI 2.2+ looks for credentials.json only in `~/.kaggle/` — `KAGGLE_CONFIG_DIR` does NOT redirect the OAuth credential lookup. When switching away from OAuth, the file is deleted.

## Auth & Credentials

### Three Auth Types

| Type | Files | Token Storage | Refresh |
|---|---|---|---|
| **Legacy Key** | `kaggle.json` with `username`+`key` | File only | N/A |
| **Access Token** | `access_token` file | Keychain via `keychain.store_token()` | Manual re-issue |
| **OAuth** | `credentials.json` with `refresh_token`/`access_token` | File only (NOT keychain) | `_refresh_oauth_token()` HTTP POST to `/api/v1/oauth2/token` |

### OAuth Flow (in `accounts.py`)

1. Creates `KaggleClient()` + `KaggleOAuth(client)`
2. Patches the OAuth success page via `_patch_oauth_success_page()` (branded Kagitch page)
3. Calls `oauth.authenticate(scopes=["resources.admin:*"])`
4. Copies `~/.kaggle/credentials.json` → `~/.kaggle-{name}/credentials.json`
5. Injects `username` into the copied credentials.json
6. Saves account with `auth_type: "oauth"`

### OAuth Token Refresh (in `checker.py:172-211`)

```python
POST https://www.kaggle.com/api/v1/oauth2/token
  grant_type=refresh_token
  refresh_token=<from credentials.json>
  client_id=kaggle-web
→ Returns (access_token, refresh_token, expires_in)
```

The refresh is called in `_check_quota_sdk()` when the stored `access_token` is expired.

## Testing Patterns

### Configuration
```toml
[tool.pytest.ini_options]
addopts = ["--cov=kaggle_switch", "--cov-report=term-missing", "--cov-fail-under=95"]
```
Tests require 95% coverage.

### Fixture Pattern (file isolation)
Every test file has a `temp_env` or `temp_config` fixture:
```python
@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / ".config" / "kagitch")
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".config" / "kagitch" / "accounts.json")
    monkeypatch.setattr(cfg, "KAGGLE_DEFAULT", tmp_path / ".kaggle")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
```

### CLI test helper (from `test_cli.py`)
```python
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
def run_cli(*args, capsys) -> tuple[int, str]:
    with patch.object(sys, "argv", ["kagitch"] + list(args)):
        rc = cli.main()
    captured = capsys.readouterr()
    return rc, _ANSI_RE.sub("", captured.out + captured.err)
```

### Mocking strategies
- **subprocess.run** → `unittest.mock.patch` with fake `CompletedProcess` return
- **keyring** → `patch("kaggle_switch.keychain.keyring")`
- **Filesystem** → `tmp_path` + `monkeypatch.setattr(Path, "home", ...)`
- **Env vars** → `monkeypatch.setenv`/`delenv`
- **kagglesdk** → `pytest.importorskip("kagglesdk")` + monkeypatched `KaggleClient`
- **requests** → Mocked `requests.post` for OAuth token refresh
- **Rich Console output** → `capsys.readouterr()` with ANSI stripping

### Env var isolation for switch tests
```python
@pytest.fixture
def temp_env(temp_env):
    saved_kcd = os.environ.get("KAGGLE_CONFIG_DIR")
    saved_kat = os.environ.get("KAGGLE_API_TOKEN")
    yield
    if saved_kcd is not None:
        os.environ["KAGGLE_CONFIG_DIR"] = saved_kcd
    else:
        os.environ.pop("KAGGLE_CONFIG_DIR", None)
    if saved_kat is not None:
        os.environ["KAGGLE_API_TOKEN"] = saved_kat
    else:
        os.environ.pop("KAGGLE_API_TOKEN", None)
```
This is needed because `_apply_account_env()` mutates `os.environ` directly.

## Common Implementation Tasks

### Adding a New Command

1. Add the handler function in the appropriate `commands/*.py` module (or create a new one)
2. Follow the function signature pattern: `def cmd_newthing(config: dict, args: list[str]) -> int:`
3. Import and re-export in `commands/__init__.py`
4. Add the if/elif branch in `cli.py:_main()` — order matters! Shorthand switch (numeric/name) comes LAST.
5. Add tests in `tests/test_cli.py` via `run_cli()` helper + dedicated test file
6. Add rendering in `display.py` if new output is needed

### Fixing Quota/Timer Issues

The TimeDeltaSerializer patch in `checker.py:20-44` is a common failure point. If you see crashes related to timedelta serialization from kagglesdk:
1. Check if `_patched_from_dict_value` is being applied
2. The fix handles whole-second values like `"0s"` (no decimal)
3. Test with `kagglesdk <= 0.1.30`

### Debugging Shell Wrapper Issues

If `kagitch switch` doesn't actually switch the shell environment:
1. Check `KAGITCH_SHELL_WRAPPER=1` is set when the command runs inside the shell function
2. Check that the `shellpath` function is installed in the correct RC file
3. Check that `eval` line matches the shell (zsh/bash vs fish vs PowerShell)
4. Reproduce by running: `KAGITCH_SHELL_WRAPPER=1 kagitch switch 2` — stdout should show `export KAGGLE_CONFIG_DIR=...`

### Adding Shell Completion for New Commands

1. Add the command and any aliases to `_all_known_tokens()` in `shell.py`
2. Add case for the new command in each shell's completion function (zsh `_kagitch`, bash `_kagitch_completions`, fish `complete`, PowerShell `Register-ArgumentCompleter`)
3. Add tests in `test_shell.py`

### Adding a New Display/Render Function

1. Add Rich content generation in `display.py` using `style.py` theme tokens
2. Use `style.console.print()` for output, never bare `print()`
3. For wrapper-mode awareness, check `os.environ.get("KAGITCH_SHELL_WRAPPER")` and use `_tty_status()` context manager for live displays
4. Add tests in `test_display.py` using `capsys.readouterr()` with ANSI stripping

## Known Gotchas & Pitfalls

### 1. kagglesdk TimeDeltaSerializer Bug (checker.py:20-44)
kagglesdk <= 0.1.30 crashes on `"0s"` input. The fix is a monkey-patch at module import. If you import kagglesdk elsewhere, ensure this patch runs first or duplicate it.

### 2. Credential Isolation (checker.py:122-137)
`KAGGLE_API_TOKEN` env var leaks between account subprocesses if not stripped. Always call `_build_env()` which pops this var. The problem is kaggle CLI 2.2+ checks `KAGGLE_API_TOKEN` before config files.

### 3. OAuth credentials.json Lookup (switch.py:60-71)
`KAGGLE_CONFIG_DIR` does NOT redirect OAuth credential lookup in kaggle CLI 2.2+. The `credentials.json` must be physically copied to `~/.kaggle/` for any command that needs OAuth auth. This is handled by `_swap_creds()` and `_run_with_creds()`.

### 4. Timezone-Naive Timestamps (checker.py:81-103)
Old `credentials.json` files may have `access_token_expiration` without timezone info. kagglesdk's timezone-aware comparison crashes on these. The `_patch_creds_expiry()` function appends `+00:00`.

### 5. Config Auto-Renumbering (config.py:88-91)
Every `load_config()` and `save_config()` renumbers accounts sequentially. Account #2 stays #2 only until the account before it is removed; then it becomes #1.

### 6. OAuth Callback Handler Patch (accounts.py:150-181)
`_patch_oauth_success_page()` replaces a kagglesdk callback with branded HTML. The guard uses `co_code` comparison to prevent double-application.

### 7. Shorthand Switch Order (cli.py:121-122)
The numeric/name shorthand check (`kagitch 2`) comes AFTER all named commands. This prevents `kagitch list` from being interpreted as switching to an account named "list". If you add a new command that could be an account name, order matters.

### 8. Wrapper Mode for kernel logs (kernel.py:474-500)
`_auto_switch_for_kernel()` temporarily switches to the owner of a kernel slug before fetching logs. This means `kagitch kernel logs owner/slug` works regardless of which account is currently active.

### 9. Platform-Specific File Permissions
`os.chmod(file, 0o600)` is guarded by `if sys.platform != "win32"` everywhere it appears.

### 10. Questionary Style Order (kernel.py:76-89)
The `selected` and `highlighted` style ordering in `_kernel_style()` is deliberate — `highlighted` must come AFTER `selected` in the list so it takes precedence on the cursor row.

## Dependencies

### Runtime (in pyproject.toml)
- `rich>=13.0` — Terminal formatting, Tables, Panels, Layout
- `keyring>=25.0` — OS keychain credential storage
- `questionary>=2.0` — Interactive prompts

### Manual install (not in pyproject.toml)
- `kaggle` — Kaggle CLI (invoked via subprocess)
- `kagglesdk` — Optional, for OAuth token refresh in checker.py
- `requests` — Used in checker.py for OAuth token refresh HTTP calls
