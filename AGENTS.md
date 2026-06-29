<!-- Generated: 2026-06-29 | Updated: 2026-06-29 -->

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

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `src/` | Application source code (see `src/AGENTS.md`) |
| `tests/` | Test suite (see `tests/AGENTS.md`) |
| `assets/` | Static assets like banners (see `assets/AGENTS.md`) |
| `.github/` | GitHub configuration and workflows (see `.github/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- This is a Python CLI project using `hatchling` as the build backend
- Entry point: `kagitch = "kaggle_switch.cli:main"`
- Requires Python 3.8+ and `rich>=13.0` for terminal output

### Testing Requirements
- Run tests with: `pytest tests/`
- Test configuration in `pyproject.toml` under `[tool.pytest.ini_options]`
- Dev dependencies: `pytest>=7.0`, `pytest-cov`

### Common Patterns
- CLI commands are defined in `src/kaggle_switch/cli.py`
- Configuration management in `src/kaggle_switch/config.py`
- Rich library used for styled terminal output
- Accounts stored in `~/.config/kagitch/accounts.json`

## Dependencies

### External
- `rich>=13.0` - Terminal formatting and styled output
- `kaggle` - Kaggle API integration (required at runtime)

### Build System
- `hatchling` - Modern Python build backend

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
