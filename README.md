
<p align="center">
  <img src="assets/banner.svg" alt="Kagitch — switch Kaggle accounts and keep your flow" width="100%">
</p>

<p align="center">
  <code>kagitch add</code> · <code>kagitch switch</code> · <code>kagitch check</code>
</p>

---

## Install

```bash
pip install git+https://github.com/TQuang122/Kagitch.git
kagitch init -r  # shell integration (one time)
```

> Requires `pip install kaggle` and Python 3.8+.

---

## Quick start

```bash
kagitch add work      # OAuth login — opens browser
kagitch add personal  # or: kagitch add personal ~/kaggle.json (legacy key)
kagitch 2             # switch to account 2
kagitch check         # check quota for all accounts
kaggle quota          # kaggle CLI follows the switched account
```

---

## Commands


| Command                     | What it does                            |
| --------------------------- | --------------------------------------- |
| `kagitch` / `list`          | List accounts                           |
| `kagitch <N>`               | Switch to account                       |
| `kagitch add <name>`        | Add account via OAuth                   |
| `kagitch add <name> <file>` | Add account via legacy API key          |
| `kagitch check`             | Check quota & auth for all accounts     |
| `kagitch current`           | Show active account                     |
| `kagitch remove <N>`        | Remove an account (deletes credentials) |
| `kagitch rename <N> <name>` | Rename an account                       |
| `kagitch init [-r]`         | Install / reload shell integration      |
| `kagitch doctor`            | System diagnostics                      |


---

## How it works

Each account lives in `~/.kaggle-<name>/`.

The shell wrapper sets `KAGGLE_CONFIG_DIR` when you switch.

**Config stored at:**

```text
~/.config/kagitch/accounts.json
```
