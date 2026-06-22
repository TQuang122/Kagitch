"""Account health checking — runs kaggle CLI under each account's config."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .config import Account, KAGGLE_DEFAULT, get_accounts, load_config


# ── Monkey-patch kagglesdk TimeDeltaSerializer ──────────────────
# kagglesdk<=0.1.30 crashes when the API returns a whole-second
# duration like "0s" (no decimal) — the split(".") produces a
# single-element list.  Patch it at import time.
try:
    from kagglesdk.kaggle_object import TimeDeltaSerializer  # type: ignore[import-untyped]
    from datetime import timedelta

    _orig = TimeDeltaSerializer._from_dict_value

    @staticmethod  # type: ignore[arg-type]
    def _patched_from_dict_value(value: object) -> timedelta | None:
        if value is None:
            return None
        v = str(value).rstrip("s")
        parts = v.split(".")
        secs = int(parts[0])
        nanos = int(parts[1]) if len(parts) > 1 else 0
        return timedelta(seconds=secs, microseconds=nanos // 1000)

    TimeDeltaSerializer._from_dict_value = _patched_from_dict_value
except Exception:
    pass  # kagglesdk not installed — quota check will fail naturally
# ────────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    number: str
    name: str
    config_path: Path
    file_ok: bool = False
    file_error: str = ""
    auth_user: str = ""
    auth_method: str = ""
    auth_match: bool = False
    gpu_remaining: str = ""
    tpu_remaining: str = ""
    quota_ok: bool = False
    quota_error: str = ""


_creds_lock = threading.Lock()


def _swap_creds(acc: Account) -> None:
    creds_dst = KAGGLE_DEFAULT / "credentials.json"
    creds_src = acc.path / "credentials.json"
    if creds_src.exists():
        creds_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(creds_src, creds_dst)
    elif creds_dst.exists():
        creds_dst.unlink()


def _run_with_creds(cmd: list[str], env: dict[str, str], acc: Account) -> subprocess.CompletedProcess:
    with _creds_lock:
        backup = KAGGLE_DEFAULT / "credentials.json"
        backup_data = backup.read_bytes() if backup.exists() else None
        try:
            _swap_creds(acc)
            return _run_kaggle(cmd, env)
        finally:
            if backup_data is not None:
                backup.write_bytes(backup_data)
            elif backup.exists():
                backup.unlink()


def _build_env(acc: Account) -> dict[str, str]:
    """Build env for kaggle subprocess.

    Strips KAGGLE_API_TOKEN so the subprocess authenticates from
    credentials.json (the swap target) instead of a possibly-stale
    shell env var set by a previous `kagitch switch`. Without this
    strip, kaggle CLI 2.2+ uses the env var token for every account,
    bypassing per-account credential isolation entirely.
    """
    env = os.environ.copy()
    env.pop("KAGGLE_API_TOKEN", None)
    if acc.is_default:
        env.pop("KAGGLE_CONFIG_DIR", None)
    else:
        env["KAGGLE_CONFIG_DIR"] = str(acc.path)
    return env


def _run_kaggle(cmd: list[str], env: dict[str, str], timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a kaggle CLI command and return the result."""
    kwargs: dict = dict(
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return subprocess.run(["kaggle"] + cmd, **kwargs)


def _require_kaggle() -> str | None:
    """Return an error string if `kaggle` CLI is not on PATH."""
    if shutil.which("kaggle"):
        return None
    return (
        "kaggle CLI not found on PATH.\n"
        "  Install with:  pip install kaggle"
    )


def check_account(acc: Account) -> CheckResult:
    """Run full check on a single account."""
    result = CheckResult(number=acc.number, name=acc.name, config_path=acc.path)
    env = _build_env(acc)

    # ── Phase 0: kaggle CLI availability ──────────────────────────
    missing = _require_kaggle()
    if missing:
        result.quota_error = missing
        result.file_error = missing
        return result

    # ── Phase 1: file check ──────────────────────────────────────
    json_file = acc.path / "kaggle.json"
    api_token = acc.path / "access_token"
    creds_file = acc.path / "credentials.json"

    if json_file.exists():
        try:
            data = json.loads(json_file.read_text())
            if "username" in data and "key" in data:
                result.file_ok = True
                result.auth_user = data["username"]
            else:
                result.file_error = "missing username/key fields"
        except (json.JSONDecodeError, OSError) as e:
            result.file_error = str(e)
    elif api_token.exists():
        result.file_ok = True
        result.auth_user = acc.name
    elif creds_file.exists():
        result.file_ok = True  # OAuth-based, no kaggle.json needed
        result.auth_user = acc.name
    else:
        result.file_error = "no credentials found"

    # ── Phase 2: auth check via kaggle config view ───────────────
    # Use _run_with_creds so the correct account's credentials are active,
    # otherwise kaggle CLI 2.2+ ignores KAGGLE_CONFIG_DIR for OAuth lookups.
    try:
        cp = _run_with_creds(["config", "view"], env, acc)
        if cp.returncode == 0:
            for line in cp.stdout.splitlines():
                line = line.strip()
                if line.startswith("- username:"):
                    result.auth_user = line.split(":", 1)[1].strip()
                elif line.startswith("- auth_method:"):
                    result.auth_method = line.split(":", 1)[1].strip()
        else:
            result.auth_match = False
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        result.quota_error = str(e)
        return result

    if creds_file.exists():
        # OAuth — credentials.json exists and config view responded
        if result.auth_method:
            result.auth_match = True
    else:
        result.auth_match = result.auth_user == acc.name

    # ── Phase 3: quota check ─────────────────────────────────────
    try:
        cp = _run_with_creds(["quota"], env, acc)
        if cp.returncode == 0:
            for line in cp.stdout.splitlines():
                line = line.strip()
                # Parse: "GPU       25.87h  4.13h      30.00h  ..."
                if line.startswith("GPU") or line.startswith("TPU"):
                    parts = line.split()
                    if len(parts) >= 3:
                        resource = parts[0]
                        remaining = parts[2]
                        if resource == "GPU":
                            result.gpu_remaining = remaining
                        elif resource == "TPU":
                            result.tpu_remaining = remaining
            result.quota_ok = True
        else:
            result.quota_error = cp.stderr[:200] if cp.stderr else f"exit code {cp.returncode}"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        result.quota_error = str(e)

    return result


def check_all_accounts(
    config: dict | None = None,
    max_workers: int = 4,
) -> list[CheckResult]:
    """Run checks on all accounts in parallel."""
    if config is None:
        config = load_config()
    accounts = get_accounts(config)
    results: list[CheckResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(check_account, acc): acc for acc in accounts}
        for future in as_completed(futures):
            results.append(future.result())

    # Sort by account number
    results.sort(key=lambda r: int(r.number))
    return results
