# Changelog

## [Unreleased]

### Added
- `kagitch kernel output [owner/slug]` — download kernel outputs. Interactive mode lists output files and lets you multi-select files or whole directories (via `questionary.checkbox`); `-a/--all` downloads everything through the kaggle CLI. Supports `-p/--path` for the target directory and `-f/--force` to overwrite existing files.
- Kernel output UI: output structure rendered as a tree with per-file sizes (parallel HEAD requests), live progress bar with speed on TTYs, and a download summary card (size, time, skipped count). Non-TTY stdin degrades gracefully with a hint to use `-a/--all`.
- `kagitch kernel output` file selection is now a single interactive tree: arrow keys navigate, right/left expand and collapse directories, space toggles a file or an entire directory subtree (with partial-state markers), Enter confirms and `q`/Ctrl-C cancels. Cross-platform raw-terminal key handling (termios on Unix, msvcrt on Windows).
- Kernel picker in `kernel output`/`kernel logs` browse mode: the full-width Rich table is gone; the interactive selector now lists slug-only rows with status colors, supports type-to-filter (substring, case-insensitive, Backspace to edit) and shows a `Kernels for <account> · N kernels` header. The output file tree picker adds an `a` key to select or deselect all files; selector footers are now in English. Kernel status colors render in the raw selector (green COMPLETE, red ERROR, yellow RUNNING, magenta CANCEL_ACKNOWLEDGED, cyan QUEUED/PENDING) - fixed an ANSI-stripping bug in the selector renderer.
### Security & reliability
- Account names are now validated (`[A-Za-z0-9._-]` only) in `add`/`rename` - blocks path traversal (`..`/`/`) that could point `kagitch remove` at arbitrary directories, and shell metacharacters that could inject into the eval-based shell wrapper.
- `kagitch update` git calls now have timeouts (30-60s) and report friendly errors instead of hanging forever; `_git_log` fails gracefully.
- The kagglesdk quota call in `kagitch check` now runs under a 15s hard timeout - a stalled SDK can no longer hang the whole check.
- The global traceback hook no longer dumps local variables (`show_locals=False`), avoiding accidental token/credential disclosure in tracebacks.
### Performance & hardening
- kagglesdk is now imported lazily (first quota check) instead of on every command - `kagitch --version`/`list` startup dropped from ~0.13s to ~0.09s. `rich.traceback` is also lazily imported.
- `accounts.json` and rewritten credentials files are chmod'd to 0600 (best-effort, non-Windows).
- Plaintext-token migration now only removes the token from `accounts.json` when the keychain write actually succeeds - no more silent token loss when keyring is unavailable.

### Changed
- `kaggle quota` fallback now parses `--format json` output first (kaggle CLI >= 2.2.3), keeping the plain-text parser only for older CLIs.
- `kagitch remove` revokes the account's Kaggle token server-side (`kaggle auth revoke`, CLI >= 2.2.4) before deleting local credentials; failure warns but never blocks removal.
- `kagitch doctor` checks the installed kaggle CLI version and warns when it is older than 2.2.4 (quota command requires >= 2.2.1).

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
