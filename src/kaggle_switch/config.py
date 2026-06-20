"""Account configuration management."""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    return base / "kagitch"


def _kaggle_default() -> Path:
    return Path.home() / ".kaggle"


CONFIG_DIR = _config_dir()
CONFIG_FILE = CONFIG_DIR / "accounts.json"
KAGGLE_DEFAULT = _kaggle_default()


@dataclass
class Account:
    number: str
    name: str
    config_dir: str  # suffix for ~/.kaggle-<suffix>; empty means default ~/.kaggle
    api_token: str = ""
    auth_type: str = ""  # "", "oauth", "token"

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
    config = json.loads(CONFIG_FILE.read_text())
    _renumber_accounts(config)
    save_config(config)  # persist compaction
    return config


def _renumber_accounts(config: dict) -> None:
    """Compact account numbers to be sequential 1, 2, 3... without gaps."""
    items = sorted(config["accounts"].items(), key=lambda x: int(x[0]))
    config["accounts"] = {str(i + 1): acc for i, (_, acc) in enumerate(items)}


def save_config(config: dict) -> None:
    _renumber_accounts(config)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


def get_accounts(config: dict) -> list[Account]:
    return [
        Account(
            number=n,
            name=acc["name"],
            config_dir=acc.get("config_dir", ""),
            api_token=acc.get("api_token", ""),
            auth_type=acc.get("auth_type", ""),
        )
        for n, acc in sorted(config["accounts"].items(), key=lambda x: int(x[0]))
    ]


def find_account(config: dict, key: str) -> Account | None:
    for n, acc in config["accounts"].items():
        if n == key or acc["name"] == key:
            return Account(
                number=n,
                name=acc["name"],
                config_dir=acc.get("config_dir", ""),
                api_token=acc.get("api_token", ""),
                auth_type=acc.get("auth_type", ""),
            )
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


def _next_account_number(config: dict) -> str:
    """Return the lowest unused account number."""
    used = {int(n) for n in config["accounts"]}
    i = 1
    while i in used:
        i += 1
    return str(i)


def add_account(config: dict, name: str, source: str | Path | None = None, auth_type: str = "") -> Account:
    """Add a new account.

    source can be:
      - None: register existing ~/.kaggle-{name}/ credentials
      - A token string starting with ``KGAT_``: save as access_token
      - A file path (string or Path): copy file into ~/.kaggle-{name}/

    auth_type: "oauth", "token", or "" (default/legacy).

    Returns the new Account. Raises ValueError if name exists.
    """
    for n, acc in config["accounts"].items():
        if acc["name"] == name:
            raise ValueError(f"Account '{name}' already exists as #{n}")

    next_n = _next_account_number(config)
    target_dir = Path.home() / f".kaggle-{name}"
    is_token = False

    if source is None:
        creds = [target_dir / "kaggle.json", target_dir / "access_token"]
        if not any(c.exists() for c in creds):
            raise FileNotFoundError(
                f"No credentials found.\n"
                f"  Provide a file:  kagitch add {name} /path/to/kaggle.json"
            )
    elif isinstance(source, str) and source.startswith("KGAT_"):
        target_dir.mkdir(parents=True, exist_ok=True)
        token_file = target_dir / "access_token"
        token_file.write_text(source + "\n")
        if sys.platform != "win32":
            os.chmod(token_file, 0o600)
        is_token = True
    else:
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {src}")
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_name = src.name if src.name in ("kaggle.json", "access_token") else "kaggle.json"
        dest = target_dir / dest_name
        shutil.copy2(src, dest)
        if sys.platform != "win32":
            os.chmod(dest, 0o600)
        if src.name not in ("kaggle.json", "access_token"):
            print(f"  Renamed {src.name} \u2192 kaggle.json", file=__import__("sys").stderr)

    entry: dict[str, str] = {"name": name, "config_dir": name}
    if is_token and isinstance(source, str):
        entry["api_token"] = source
    if auth_type:
        entry["auth_type"] = auth_type
    config["accounts"][next_n] = entry
    save_config(config)
    return Account(number=next_n, name=name, config_dir=name, api_token=source if is_token else "", auth_type=auth_type)


def remove_account(config: dict, key: str) -> Account:
    """Remove an account by number or name. Returns the removed Account. Raises KeyError if not found."""
    account = find_account(config, key)
    if account is None:
        raise KeyError(f"Account '{key}' not found")
    del config["accounts"][account.number]
    save_config(config)
    if account.config_dir:
        if account.path.exists():
            shutil.rmtree(account.path)
    return account


def rename_account(config: dict, key: str, new_name: str) -> Account:
    """Rename an account. Returns the updated Account."""
    account = find_account(config, key)
    if account is None:
        raise KeyError(f"Account #{key} not found")
    config["accounts"][account.number]["name"] = new_name
    save_config(config)
    return Account(number=account.number, name=new_name, config_dir=account.config_dir)

