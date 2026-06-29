<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-29 | Updated: 2026-06-29 -->

# src

## Purpose
Application source code root containing the `kaggle_switch` Python package.

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `kaggle_switch/` | Main Python package with CLI, config, and utilities (see `kaggle_switch/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Source is organized as a single package: `kaggle_switch`
- Use `src/` layout per PEP 517/518 conventions
- Entry point defined in `pyproject.toml`: `kagitch = "kaggle_switch.cli:main"`

### Testing Requirements
- Run from project root: `pytest tests/`
- Tests mirror source structure: `test_cli.py`, `test_config.py`, etc.

### Common Patterns
- Package uses `from __future__ import annotations` for modern type hints
- Rich library for all terminal output (no print statements)
- Dataclasses for structured data (Account, CheckResult)

## Dependencies

### Internal
- All modules import from within `kaggle_switch` package

### External
- `rich` - Terminal formatting
- `kaggle` - Kaggle API (runtime dependency)

<!-- MANUAL: -->
