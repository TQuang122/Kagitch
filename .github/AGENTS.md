<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-29 | Updated: 2026-06-29 -->

# .github

## Purpose
GitHub configuration files for CI/CD workflows, issue templates, and repository management.

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `workflows/` | GitHub Actions CI/CD pipelines (see `workflows/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Contains GitHub Actions workflow definitions
- Workflows run on push/PR to main/master branches
- Use standard GitHub Actions syntax

### Testing Requirements
- Workflows are tested by GitHub Actions on push/PR
- Local testing not applicable

### Common Patterns
- YAML-based workflow definitions
- Matrix builds for multi-platform/Python version testing

## Dependencies

### Internal
- Workflows reference project structure and test commands

### External
- GitHub Actions runners (ubuntu-latest, macos-latest)

<!-- MANUAL: -->
