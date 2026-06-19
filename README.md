# kaggle-switch

Kaggle multi-account manager. Switch between multiple Kaggle accounts with a single command.

## Why

Kaggle gives each account 30h GPU / 20h TPU per week. When you burn through one account's quota, you switch to another. `kaggle-switch` makes this painless — no manual `KAGGLE_CONFIG_DIR` exports, no renaming `kaggle.json` files.

## Install

```bash
# pipx (recommended — isolated environment)
pipx install git+https://github.com/USER/kaggle-switch.git

# uv
uv tool install git+https://github.com/USER/kaggle-switch.git

# pip
pip install git+https://github.com/USER/kaggle-switch.git
```

## Shell integration (one-time setup)

After installing, run:

```bash
kaggle-switch init
```

This detects your shell (zsh/bash/fish) and appends the integration line to your rc file (`~/.zshrc`, `~/.bashrc`, or `~/.config/fish/config.fish`).

Then restart your shell or source the rc file:

```bash
source ~/.zshrc  # or ~/.bashrc
```

### Manual setup

If you prefer manual setup, add this line to your shell rc file:

**zsh / bash:**
```bash
eval "$(kaggle-switch shellpath zsh)"
```

**fish:**
```fish
kaggle-switch shellpath fish | source
```

## Usage

### Add accounts

Get your `kaggle.json` from https://www.kaggle.com/settings → Account → API → Create New Token.

```bash
kaggle-switch add work ~/Downloads/kaggle.json
kaggle-switch add personal ~/Downloads/kaggle2.json
```

### List accounts

```bash
kaggle-switch
# or
kaggle-switch list
```

Output:
```
#    Name                 Config Dir                                        Status
──── ──────────────────── ────────────────────────────────────────────────── ────────
1    work                 /home/user/.kaggle-work                           ● active
2    personal             /home/user/.kaggle-personal
```

### Switch accounts

```bash
kaggle-switch 2
# Switched to account 2
```

After switching, all `kaggle` commands use the selected account:

```bash
kaggle quota
kaggle kernels push
kaggle datasets download
```

### Other commands

```bash
kaggle-switch current         # show active account
kaggle-switch remove 2        # remove account by number or name
kaggle-switch rename 1 office # rename account
kaggle-switch --version
kaggle-switch --help
```

## How it works

`kaggle-switch` manages account configs in `~/.config/kaggle-switch/accounts.json`. Each account's `kaggle.json` lives in `~/.kaggle-<name>/`. The shell function sets `KAGGLE_CONFIG_DIR` so the `kaggle` CLI reads from the right directory.

```
~/.config/kaggle-switch/accounts.json    # account registry
~/.kaggle-work/kaggle.json               # account 1 credentials
~/.kaggle-personal/kaggle.json           # account 2 credentials
```

## Requirements

- Python 3.8+
- No runtime dependencies

## Development

```bash
git clone https://github.com/USER/kaggle-switch.git
cd kaggle-switch
pip install -e ".[dev]"
pytest
```

## License

MIT
