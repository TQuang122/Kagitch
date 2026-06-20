# Changelog

## [Unreleased]

### Changed
- Made direct `kagitch switch` output human-friendly while keeping machine-readable env output for shell wrappers.
- Improved `kagitch switch` picker validation for invalid account choices.
- Added a README terminal snippet for the dashboard.

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
