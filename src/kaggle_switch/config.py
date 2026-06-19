"""Account configuration management."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "kaggle-switch"
CONFIG_FILE = CONFIG_DIR / "accounts.json"
KAGGLE_DEFAULT = Path.home() / ".kaggle"

MARKER = "__KAGGLE_SWITCH__"


@dataclass
class Account:
    number: str
    name: str
    config_dir: str  # suffix for ~/.kaggle-<suffix>; empty means default ~/.kaggle

    @property
    def path(self) -> Path:
        if not self.config_dir:
            return KAGGLE_DEFAULT
        return Path.home() / f".kaggle-{self.config_dir}"

    @property
    def is_default(self) -> bool:
        return not self.config_dir


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {"accounts": {}}
    return json.loads(CONFIG_FILE.read_text())


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


def get_accounts(config: dict) -> list[Account]:
    return [
        Account(number=n, name=acc["name"], config_dir=acc.get("config_dir", ""))
        for n, acc in sorted(config["accounts"].items(), key=lambda x: int(x[0]))
    ]


def find_account(config: dict, key: str) -> Account | None:
    for n, acc in config["accounts"].items():
        if n == key or acc["name"] == key:
            return Account(number=n, name=acc["name"], config_dir=acc.get("config_dir", ""))
    return None


def current_active(config: dict) -> str | None:
    """Return the active account number based on KAGGLE_CONFIG_DIR env var."""
    kcd = os.environ.get("KAGGLE_CONFIG_DIR", "")
    if not kcd:
        return "1"  # default account
    for n, acc in config["accounts"].items():
        suffix = acc.get("config_dir", "")
        if suffix and kcd.endswith(suffix):
            return n
    return None


def add_account(config: dict, name: str, kaggle_json_path: Path | None = None) -> Account:
    """Add a new account. Returns the new Account. Raises ValueError if name exists."""
    for n, acc in config["accounts"].items():
        if acc["name"] == name:
            raise ValueError(f"Account '{name}' already exists as #{n}")

    nums = [int(n) for n in config["accounts"]]
    next_n = str(max(nums) + 1) if nums else "1"

    if kaggle_json_path is not None:
        if not kaggle_json_path.exists():
            raise FileNotFoundError(f"File not found: {kaggle_json_path}")
        target_dir = Path.home() / f".kaggle-{name}"
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kaggle_json_path, target_dir / "kaggle.json")
        os.chmod(target_dir / "kaggle.json", 0o600)
    else:
        target_dir = Path.home() / f".kaggle-{name}"
        if not (target_dir / "kaggle.json").exists():
            raise FileNotFoundError(
                f"Neither kaggle.json path provided nor ~/.kaggle-{name}/kaggle.json found.\n"
                f"Provide the path: kaggle-switch add {name} /path/to/kaggle.json"
            )

    config["accounts"][next_n] = {"name": name, "config_dir": name}
    save_config(config)
    return Account(number=next_n, name=name, config_dir=name)


def remove_account(config: dict, key: str) -> Account:
    """Remove an account by number or name. Returns the removed Account. Raises KeyError if not found."""
    account = find_account(config, key)
    if account is None:
        raise KeyError(f"Account '{key}' not found")
    del config["accounts"][account.number]
    save_config(config)
    return account


def rename_account(config: dict, key: str, new_name: str) -> Account:
    """Rename an account. Returns the updated Account."""
    account = find_account(config, key)
    if account is None:
        raise KeyError(f"Account #{key} not found")
    config["accounts"][account.number]["name"] = new_name
    save_config(config)
    return Account(number=account.number, name=new_name, config_dir=account.config_dir)


def switch_marker(account: Account) -> str:
    """Return the marker string for the shell function to parse."""
    if account.is_default:
        return MARKER
    return f"{MARKER}{account.path}"
