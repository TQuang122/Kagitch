<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-29 | Updated: 2026-07-08 -->

# kaggle_switch

## Purpose
Main Python package implementing the Kagitch CLI tool for managing multiple Kaggle accounts.

## Key Files
| File | Description |
|------|-------------|
| `cli.py` | Thin CLI dispatch layer (~80 lines) — delegates to `commands/` |
| `commands/` | Command handler modules (accounts, kernel, doctor, setup, switch) |
| `config.py` | Account configuration management and persistence |
| `checker.py` | Account health checking and quota verification |
| `shell.py` | Shell integration (completions, RC file setup, env vars) |
| `keychain.py` | OS keychain credential storage via `keyring` |
| `init_wizard.py` | Interactive 7-step setup wizard for first-time users |
| `logs_viewer.py` | TUI kernel log viewer with Rich Layout split-pane |
| `style.py` | Rich-based terminal styling and formatting constants |
| `__init__.py` | Package version and public API exports |

## For AI Agents

### Working In This Directory
- Entry point: `cli.py:main()` dispatches via if/elif chain on `sys.argv`
- Config stored at `~/.config/kagitch/accounts.json` (Linux/macOS) or `%APPDATA%/kagitch/accounts.json` (Windows)
- Each Kaggle account lives in `~/.kaggle-<name>/` with its own `kaggle.json`
- All terminal output goes through Rich (Console, Table, Panel, Layout)
- `from __future__ import annotations` used throughout for PEP 604 compat

### Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Thin dispatch (~80 lines) — parses argv, routes to `commands/` handlers |
| `commands/` | Command handler subpackage — one module per domain (accounts, kernel, doctor, setup, switch) |
| `config.py` | CRUD operations for account metadata (dataclass + JSON persistence) |
| `checker.py` | Parallel quota/auth checks via `kaggle` subprocess + kagglesdk OAuth |
| `shell.py` | Shell autodetection, RC file management, completions scripts, eval-line injection |
| `keychain.py` | `keyring`-backed token storage (one entry per account) |
| `init_wizard.py` | 7-step interactive setup (shell detect → config → env → kaggle → shell setup → account → summary) |
| `logs_viewer.py` | Live kernel log TUI with Rich Layout, scrollback, keybindings |
| `style.py` | Theme colors, styled Console, Panel/Table factory helpers |

### Critical Patterns & Gotchas

#### CLI Dispatch
- `main()` inspects `sys.argv` directly in an if/elif chain — NOT Click/argparse
- Command functions live in `commands/` subpackage; `cli.py` imports and dispatches only
- `--help` is pattern-matched early; positional args use simple string comparisons

#### Shell Integration
- Switching accounts injects `export KAGGLE_CONFIG_DIR=~/.kaggle-<name>/` via shell `eval`
- This means `kagitch switch` prints a shell snippet, and the user's shell config `eval`s it
- On Windows PowerShell, uses `$PROFILE` and `$env:KAGGLE_CONFIG_DIR`
- Shell autodetection checks `$SHELL`, `$PSVersionTable`, `$fish_prompt`

#### OAuth & Keychain
- OAuth tokens stored in OS keychain via `keyring`, NOT in `accounts.json`
- `accounts.json` only stores metadata (name, auth_service, config_dir path)
- Token refresh uses `kagglesdk` for OAuth validation, falls back to checking `kaggle` CLI exit code
- Legacy accounts use a `kaggle.json` file path instead of OAuth

#### The kagglesdk Patch (`checker.py`)
- `kagglesdk` has a serialization bug with `TimeDeltaSerializer` for whole-second durations
- `checker.py` patches this at module level by replacing `kagglesdk.common.sessions.TimeDeltaSerializer`
- If you touch anything related to time duration serialization, check this patch first

#### Logs Viewer
- Uses Rich `Layout` with a header pane and a scrollable main pane
- Streams kernel logs via `kaggle kernels status` subprocess
- Keyboard shortcuts for refresh, quit, scroll

### Testing Requirements
- Tests in `tests/` directory at project root
- Run: `pytest tests/ -v`
- Mock: `subprocess.run`, `keyring`, filesystem ops, `kagglesdk`
- Use `monkeypatch.setattr` for env vars; `tmp_path` for temp config dirs

## Dependencies

### Internal
- `style.py` — Imported by every other module for terminal output
- `config.py` — Imported by commands/* modules, checker.py, shell.py, keychain.py
- `shell.py` — Imported by commands/* modules, init_wizard.py
- `commands/` — Five modules (accounts, doctor, kernel, setup, switch) imported by cli.py

### Runtime (in pyproject.toml)
- `rich>=13.0` — Terminal formatting
- `keyring>=25.0` — OS keychain credential storage
- `questionary>=2.0` — Interactive prompts

### Runtime (manual install)
- `kaggle` — Kaggle CLI invoked via subprocess (NOT in pyproject.toml)
- `kagglesdk` — Optional, used only for OAuth token refresh in checker.py

<!-- MANUAL: -->
