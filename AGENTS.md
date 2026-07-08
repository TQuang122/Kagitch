<!-- Generated: 2026-06-29 | Updated: 2026-07-08 -->

# kaggle-switch

## Purpose
Kagitch — a CLI tool for managing multiple Kaggle accounts. Switch between accounts with one command, check quota, and manage credentials seamlessly.

## Key Files
| File | Description |
|------|-------------|
| `pyproject.toml` | Project configuration, dependencies, and build settings |
| `README.md` | User documentation with installation and usage instructions |
| `CHANGELOG.md` | Version history and release notes |
| `LICENSE` | MIT license |
| `uv.lock` | Dependency lock file for reproducible builds |
| `src/kaggle_switch/cli.py` | Thin CLI dispatch layer (~80 lines) — delegates to `commands/` package |
| `src/kaggle_switch/commands/` | Command handler modules (accounts, kernel, doctor, setup, switch) |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `src/` | Application source code (see `src/AGENTS.md`) |
| `tests/` | Test suite (see `tests/AGENTS.md`) |
| `assets/` | Static assets like banners (see `assets/AGENTS.md`) |
| `.github/` | GitHub configuration and workflows (see `.github/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Python CLI project using `hatchling` as the build backend
- Entry point: `kagitch = "kaggle_switch.cli:main"`, requires Python >= 3.8
- Install: `pip install -e ".[dev]"`, test: `pytest -v`
- CI: GitHub Actions on ubuntu-latest + macos-latest, Python 3.8-3.13 (see `.github/workflows/ci.yml`)

### Key Architecture
- **Account isolation** via `KAGGLE_CONFIG_DIR` env var — each account has `~/.kaggle-<name>/`
- **Switching** works by injecting `export KAGGLE_CONFIG_DIR=...` via shell `eval`
- **Token storage** uses OS keychain via `keyring` library (not files)
- **Config** stored at `~/.config/kagitch/accounts.json` (Linux/macOS) or `%APPDATA%/kagitch/accounts.json` (Windows)
- **OAuth flow**: opens browser for Kaggle auth, stores refresh token in keychain
- **Legacy auth**: supports importing API keys from `kaggle.json` files

### Common Patterns & Gotchas
- All terminal output uses `rich` (Console, Table, Panel) — never bare `print()`
- `kaggle` CLI is invoked via `subprocess.run()`, NOT the `kagglesdk` directly (except for token refresh)
- `kagglesdk` has a known `TimeDeltaSerializer` bug for whole-second durations — patched in `checker.py`
- Shell integration is the trickiest part: uses `eval`-line injection for env vars; Windows PowerShell uses `$PROFILE`
- Account switching sets `KAGGLE_CONFIG_DIR` to `~/.kaggle-<name>/` — this makes `kaggle` CLI use the right credentials
- Config directory permissions matter: `accounts.json` stores account metadata (names, paths), not secrets
- The `patch` command modifies `kernel-metadata.json` to update the Kaggle notebook ID for the active account
- All modules use `from __future__ import annotations` for PEP 604 style hints (Python 3.8+ compat)
- `checker.py` uses `concurrent.futures.ThreadPoolExecutor` for parallel quota checks across accounts

### Testing Requirements
- Run tests with: `pytest tests/ -v`
- Test configuration in `pyproject.toml` under `[tool.pytest.ini_options]`
- Dev dependencies: `pytest>=7.0`, `pytest-cov`
- Tests mock: filesystem, subprocess calls, `keyring` backend, kaggle CLI responses

## Dependencies

### Runtime (in pyproject.toml)
- `rich>=13.0` — Terminal formatting and styled output
- `keyring>=25.0` — OS keychain credential storage
- `questionary>=2.0` — Interactive prompts in wizard

### Runtime (manual install required)
- `kaggle` — Kaggle CLI (invoked via subprocess). NOT in pyproject.toml; user must `pip install kaggle` separately.

### Build System
- `hatchling` — Modern Python build backend

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
