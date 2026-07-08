<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-29 | Updated: 2026-07-08 -->

# tests

## Purpose
Test suite for the Kagitch CLI tool, covering CLI commands, configuration management, shell integration, account checking, keychain operations, init wizard, logs viewer, and shell integration.

## Key Files
| File | Description |
|------|-------------|
| `test_cli.py` | CLI command tests (574 lines) — all user-facing commands |
| `test_config.py` | Configuration module tests (220 lines) — CRUD operations |
| `test_checker.py` | Account health checking tests |
| `test_shell.py` | Shell integration tests (completions, RC files, env vars) |
| `test_keychain.py` | OS keychain credential storage tests |
| `test_init_wizard.py` | Interactive setup wizard tests |
| `test_logs_viewer.py` | Kernel log viewer TUI tests |

## For AI Agents

### Working In This Directory
- Run all tests: `pytest tests/ -v`
- Run specific test: `pytest tests/test_cli.py -v -k "test_name"`
- Tests use `pytest` fixtures extensively (`tmp_path`, `monkeypatch`)
- External calls are mocked: filesystem, subprocess, `keyring`, kaggle API
- ANSI stripping via `_ANSI_RE` regex for output assertion
- Mock `keyring` backend to avoid real OS keychain access

### Testing Requirements
- Coverage target: >80% (run with `pytest --cov`)
- Mock all external dependencies in tests
- Use `monkeypatch.setattr` for env var isolation
- Tests create temporary directories for config/filesystem operations
- Mock `subprocess.run` for any kaggle CLI invocation

### Common Patterns
- **Fixtures**: `temp_env` and `temp_config` for isolated test environments
- **Mocking**: `unittest.mock.patch` for filesystem, subprocess, keyring
- **CLI testing**: `run_cli()` helper captures stdout/stderr via `capsys`
- **ANSI stripping**: `_ANSI_RE` regex removes color codes for plain-text assertions
- **Keychain mocking**: patch `keyring.get_password`/`set_password` to avoid OS credential store

### Test Organization

| Test File | Coverage |
|-----------|----------|
| `test_cli.py` | All CLI commands: list, switch, add, remove, rename, check, doctor, init, patch, current |
| `test_config.py` | Config CRUD: load, save, add_account, remove_account, find_account, rename_account |
| `test_checker.py` | Account validation, quota checking, OAuth token refresh, kagglesdk patching |
| `test_shell.py` | Shell detection (bash/zsh/fish/pwsh), RC file management, completions generation, eval-line injection |
| `test_keychain.py` | Token save/retrieve/delete via keyring, fallback behavior |
| `test_init_wizard.py` | Step-by-step wizard flow, shell setup, account creation, error handling |
| `test_logs_viewer.py` | Kernel log streaming, layout rendering, keyboard shortcuts |

## Dependencies

### Internal
- Tests import from `kaggle_switch` package modules directly

### External
- `pytest>=7.0` — Test framework
- `pytest-cov` — Coverage reporting

<!-- MANUAL: -->
