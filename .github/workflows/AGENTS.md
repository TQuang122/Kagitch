<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-29 | Updated: 2026-06-29 -->

# workflows

## Purpose
GitHub Actions CI/CD workflow definitions for automated testing and deployment.

## Key Files
| File | Description |
|------|-------------|
| `ci.yml` | Main CI pipeline - runs tests on push/PR |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| (none) | Single workflow file |

## For AI Agents

### Working In This Directory
- Workflow triggers: push/PR to main/master
- Matrix strategy: Ubuntu + macOS, Python 3.8-3.13
- Install command: `pip install -e ".[dev]"`
- Test command: `pytest -v`

### Testing Requirements
- Workflows are tested by GitHub Actions
- No local testing needed

### Common Patterns
- `actions/checkout@v4` for repo checkout
- `actions/setup-python@v5` for Python setup
- Matrix builds for cross-platform compatibility
- `fail-fast: false` to run all matrix combinations

### Workflow Structure

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python-version: ["3.8", "3.9", "3.10", "3.11", "3.12", "3.13"]
    steps:
      - checkout
      - setup-python
      - install
      - run tests
```

## Dependencies

### Internal
- References project's `pyproject.toml` for dependencies
- Runs `pytest` from project root

### External
- GitHub Actions runners
- Python 3.8-3.13

<!-- MANUAL: -->
