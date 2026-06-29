<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-29 | Updated: 2026-06-29 -->

# kaggle_switch

## Purpose
Main Python package implementing the Kagitch CLI tool for managing multiple Kaggle accounts.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Package version and public API exports |
| `cli.py` | CLI entry point with all commands (1244 lines) |
| `config.py` | Account configuration management and persistence |
| `checker.py` | Account health checking and quota verification |
| `shell.py` | Shell integration (completions, RC file setup, env vars) |
| `style.py` | Rich-based terminal styling and formatting utilities |
| `init_wizard.py` | Interactive setup wizard for first-time users |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| (none) | Flat package structure - all modules at package level |

## For AI Agents

### Working In This Directory
- Entry point: `cli.py:main()` function
- Config stored at `~/.config/kagitch/accounts.json`
- Each Kaggle account lives in `~/.kaggle-<name>/`
- Use `rich` for all terminal output (Console, Table, Panel)

### Testing Requirements
- Tests in `tests/` directory at project root
- Run: `pytest tests/test_cli.py tests/test_config.py`
- Mock external calls (kaggle API, filesystem) in tests

### Common Patterns
- **CLI commands**: Function-based with decorators in `cli.py`
- **Config**: JSON-based with dataclass `Account` model
- **Shell integration**: `eval` line injection for account switching
- **Error handling**: Rich error panels with styled output
- **Type hints**: Modern Python with `from __future__ import annotations`

### Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Command parsing, user interaction, orchestration |
| `config.py` | CRUD operations for account configuration |
| `checker.py` | Parallel quota/auth checking via kaggle CLI |
| `shell.py` | Shell detection, RC file management, completions |
| `style.py` | Color constants, styled console output |
| `init_wizard.py` | Step-by-step interactive setup |

## Dependencies

### Internal
- `style.py` → Used by all modules for terminal output
- `config.py` → Used by `cli.py` and `checker.py`
- `shell.py` → Used by `cli.py` for shell integration

### External
- `rich>=13.0` - Terminal formatting (Console, Table, Panel, Prompt)
- `kaggle` - Kaggle CLI (invoked via subprocess)
- `kagglesdk` - Optional SDK for OAuth token validation

<!-- MANUAL: -->
