<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-29 | Updated: 2026-06-29 -->

# tests

## Purpose
Test suite for the Kagitch CLI tool, covering CLI commands, configuration management, shell integration, and account checking.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Test package marker |
| `test_cli.py` | CLI command tests (574 lines) - all user-facing commands |
| `test_config.py` | Configuration module tests (220 lines) - CRUD operations |
| `test_checker.py` | Account health checking tests |
| `test_shell.py` | Shell integration tests (completions, RC files, env vars) |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| (none) | Flat test structure - tests at package level |

## For AI Agents

### Working In This Directory
- Run all tests: `pytest tests/`
- Run specific test: `pytest tests/test_cli.py -v`
- Tests use `pytest` fixtures extensively (tmp_path, monkeypatch)
- External calls are mocked (filesystem, subprocess, kaggle API)

### Testing Requirements
- Coverage target: >80% (run with `pytest --cov`)
- Mock all external dependencies in tests
- Use `monkeypatch` to isolate test environments
- Tests create temporary directories for config/filesystem operations

### Common Patterns
- **Fixtures**: `temp_env` and `temp_config` for isolated test environments
- **Mocking**: `unittest.mock.patch` for filesystem and subprocess calls
- **CLI testing**: `run_cli()` helper captures stdout/stderr
- **ANSI stripping**: `_ANSI_RE` regex removes color codes for assertion

### Test Organization

| Test File | Coverage |
|-----------|----------|
| `test_cli.py` | All CLI commands: list, switch, add, remove, rename, check, doctor, init |
| `test_config.py` | Config CRUD: load, save, add_account, remove_account, find_account |
| `test_checker.py` | Account validation, quota checking, OAuth token refresh |
| `test_shell.py` | Shell detection, RC file management, completions generation |

## Dependencies

### Internal
- Tests import from `kaggle_switch` package
- Use same modules as production code

### External
- `pytest` - Test framework
- `pytest-cov` - Coverage reporting

<!-- MANUAL: -->
