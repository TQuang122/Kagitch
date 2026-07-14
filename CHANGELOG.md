# Changelog

## [1.5.1] - 2026-07-14

### Fixed
- Windows terminal selectors now support both extended-key prefixes used by console environments for arrow keys.
- `kagitch kernel logs` now keeps interactive account and kernel selection working in PowerShell and other shell wrappers.
- Windows selection falls back safely when a controlling `CON` device is unavailable.

## [1.5.0] - 2026-07-12

### Added
- ASCII table detection in kernel logs — pipe-delimited tables (pandas `value_counts()`, `crosstab()`, etc.) are now rendered as Rich Tables.
- Phase detection headers — major workflow stages (Setup, Dependencies, Training, Validation, Inference) are highlighted with styled separators.
- `--errors-only` / `-e` flag — show only error-classified lines.
- `--summary` flag — show only errors, warnings, and metrics (hide verbose noise).
- `--no-group` flag — disable section separators and duplicate line collapsing.
- Result summary panel — error/warning counts and total lines displayed after log output.
- Kernel info header — kernel name, runtime duration, and status displayed before log content.
- Duplicate consecutive lines are collapsed with a repeat count.
- OAuth `credentials.json` now includes the `username` field for downstream readers.

### Changed
- `render_logs()` now returns `(error_count, warning_count, total)` instead of `None`.
- Long log lines are truncated at 260 characters (with a `(+N)` overflow indicator) for readability.
- `render_result()` accepts `kernel_ref` to show a header panel.

## [1.4.1] - 2026-07-10

### Fixed
- Handle empty config file gracefully (fixes crash on first `kagitch` run on Windows).

### Changed
- Published to PyPI — install via `pip install kagitch`.

## [1.4.0] - 2026-07-10

### Added
- CI auto-publish to PyPI via GitHub Actions on version tags.
- OAuth success page now auto-closes browser tab after 3 seconds.

### Changed
- Made direct `kagitch switch` output human-friendly while keeping machine-readable env output for shell wrappers.
- Improved `kagitch switch` picker validation for invalid account choices.
- Added a README terminal snippet for the dashboard.
- Polished OAuth success page brand with gradient text, terminal prompt, and blinking cursor.

## [1.1.0] - 2026-06-21

### Added
- Added a default dashboard for bare `kagitch`, showing the active account and account table.
- Added an interactive `kagitch switch` account picker when no account argument is provided.
- Added a `kagitch doctor` status summary with structured diagnostics and actionable recommendations.
- Added Windows/PowerShell profile handling for both Windows PowerShell 5.1 and PowerShell 7+.
- Added `kagitch update` for pulling the latest git-installed version.
- Added shell completion aliases and help/version shortcuts.

### Fixed
- Fixed OAuth account switching so `credentials.json` is copied into the default Kaggle config location before quota checks.
- Fixed help panel rendering and border alignment.
- Fixed the shell wrapper known-command list for `update`.
- Removed fragile doctor version-marker staleness detection that could report false positives.
- Fixed README command table rendering for commands containing `|`.

### Changed
- Centralized shell command, alias, and flag definitions into a single source of truth.
- Improved README and CLI help text for Windows/PowerShell and the new dashboard/switch behavior.
