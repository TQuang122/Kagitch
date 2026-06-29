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
from datetime import datetime, timedelta
from pathlib import Path

from .config import Account, KAGGLE_DEFAULT, get_accounts, load_config

_OAUTH_TOKEN_URL = "https://www.kaggle.com/api/v1/oauth2/token"


# ── kagglesdk imports & TimeDeltaSerializer fix ────────────────
# kagglesdk<=0.1.30 crashes when the API returns a whole-second
# duration like "0s" (no decimal) — the split(".") produces a
# single-element list.  Patch it at import time.
_HAS_SDK = False
try:
    from kagglesdk import KaggleClient
    from kagglesdk.kaggle_object import TimeDeltaSerializer  # type: ignore[import-untyped]

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
    _HAS_SDK = True
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
    quota_refresh: str = ""
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


def _patch_creds_expiry(path: Path | None = None) -> None:
    """Ensure access_token_expiration in a credentials.json is timezone-aware.

    kagglesdk internally compares the stored expiration against
    ``datetime.now(timezone.utc)`` (aware), but old code wrote naive
    ISO timestamps via ``datetime.now().isoformat()``.  A naive-vs-aware
    comparison crashes the kaggle CLI at import time with TypeError.

    When *path* is provided (e.g. an account's source credentials.json),
    the file is patched in-place.  When omitted, ``KAGGLE_DEFAULT / credentials.json``
    is patched.
    """
    creds = path or (KAGGLE_DEFAULT / "credentials.json")
    if not creds.exists():
        return
    try:
        data = json.loads(creds.read_text())
        exp = data.get("access_token_expiration", "")
        if exp and "+" not in exp and exp.endswith("Z") is False:
            # Naive datetime — assume UTC and make it explicit.
            data["access_token_expiration"] = exp.rstrip("Z") + "+00:00"
            creds.write_text(json.dumps(data, indent=2))
    except (json.JSONDecodeError, OSError):
        pass


def _run_with_creds(cmd: list[str], env: dict[str, str], acc: Account) -> subprocess.CompletedProcess:
    with _creds_lock:
        backup = KAGGLE_DEFAULT / "credentials.json"
        backup_data = backup.read_bytes() if backup.exists() else None
        try:
            _swap_creds(acc)
            _patch_creds_expiry()
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


def _td(td: timedelta | None) -> str:
    if td is None:
        return "n/a"
    total = td.total_seconds()
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    return f"{h}h{m:02d}m"


def _refresh_oauth_token(acc: Account) -> tuple[str, str, str] | None:
    """Use the refresh_token in credentials.json to get a fresh access token.

    Returns (access_token, refresh_token, expires_in_seconds) or None.
    """
    creds_file = acc.path / "credentials.json"
    if not creds_file.exists():
        return None
    try:
        data = json.loads(creds_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return None

    try:
        import requests as _req

        resp = _req.post(
            _OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": "kaggle-web",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        new_data = resp.json()
        new_token = new_data.get("access_token") or new_data.get("accessToken")
        if not new_token or len(new_token) <= 20:
            return None
        new_refresh = new_data.get("refresh_token") or new_data.get("refreshToken")
        new_expires_in = new_data.get("expiresIn") or new_data.get("expires_in", 10800)
        return (new_token, new_refresh, new_expires_in)
    except Exception:
        return None



def _check_quota_sdk(
    env: dict[str, str], acc: Account
) -> tuple[str, str, str, bool, str]:
    """
    Use kagglesdk to query accelerator quota.

    Returns (gpu_remaining, tpu_remaining, quota_refresh, ok, error).
    """
    if not _HAS_SDK:
        return ("", "", "", False, "kagglesdk not available")

    with _creds_lock:
        backup = KAGGLE_DEFAULT / "credentials.json"
        backup_data = backup.read_bytes() if backup.exists() else None
        try:
            _swap_creds(acc)
            _patch_creds_expiry()

            # Try OAuth token (credentials.json), then fall back to legacy
            # API key (kaggle.json with username+key)
            client: KaggleClient | None = None
            creds_file = KAGGLE_DEFAULT / "credentials.json"
            if creds_file.exists():
                try:
                    data = json.loads(creds_file.read_text())
                    token = data.get("access_token")
                    if token:
                        exp_str = data.get("access_token_expiration")
                        expired = True
                        if exp_str:
                            try:
                                exp = datetime.fromisoformat(exp_str)
                                now = datetime.now(
                                    exp.tzinfo if exp.tzinfo else None
                                )
                                expired = exp <= now
                            except (ValueError, TypeError):
                                pass
                        if expired:
                            result = _refresh_oauth_token(acc)
                            if result is not None:
                                new_token, new_refresh, expires_in = result
                                token = new_token
                                data["access_token"] = new_token
                                if new_refresh:
                                    data["refresh_token"] = new_refresh
                                data["access_token_expiration"] = (
                                    datetime.now(datetime.UTC)
                                    + timedelta(seconds=expires_in - 60)
                                ).isoformat()
                                creds_file.write_text(
                                    json.dumps(data, indent=2)
                                )
                        client = KaggleClient(api_token=token)
                except (json.JSONDecodeError, OSError, KeyError):
                    pass

            if client is None:
                kaggle_file = KAGGLE_DEFAULT / "kaggle.json"
                if kaggle_file.exists():
                    try:
                        kdata = json.loads(kaggle_file.read_text())
                        username = kdata.get("username")
                        key = kdata.get("key")
                        if username and key:
                            client = KaggleClient(
                                username=username, password=key
                            )
                    except (json.JSONDecodeError, OSError):
                        pass

            if client is None:
                return ("", "", "", False, "no credentials found")

            resp = client.kernels.kernels_api_client.get_accelerator_quota_statistics()

            gpu_q = resp.gpu_quota
            tpu_q = resp.tpu_quota
            if gpu_q is not None and gpu_q.total_time_allowed is not None:
                remaining = (gpu_q.total_time_allowed - (gpu_q.time_used or timedelta())).total_seconds() / 3600
                gpu_remaining = f"{remaining:.2f}h"
            else:
                gpu_remaining = "n/a"

            if tpu_q is not None and tpu_q.total_time_allowed is not None:
                remaining = (tpu_q.total_time_allowed - (tpu_q.time_used or timedelta())).total_seconds() / 3600
                tpu_remaining = f"{remaining:.2f}h"
            else:
                tpu_remaining = "n/a"

            refresh = resp.quota_refresh_time
            refresh_str = refresh.isoformat() if refresh is not None else ""

            return (gpu_remaining, tpu_remaining, refresh_str, True, "")

        except Exception as e:
            err = str(e)
            if len(err) > 200:
                err = err[:200]
            return ("", "", "", False, err)
        finally:
            if backup_data is not None:
                backup.write_bytes(backup_data)
            elif backup.exists():
                backup.unlink()


def check_account(acc: Account) -> CheckResult:
    """Run full check on a single account."""
    result = CheckResult(number=acc.number, name=acc.name, config_path=acc.path)
    env = _build_env(acc)

    _patch_creds_expiry(acc.path / "credentials.json")

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
    # Try kagglesdk first (handles OAuth token refresh), fall back to
    # kaggle CLI subprocess for legacy API key accounts.
    (
        result.gpu_remaining,
        result.tpu_remaining,
        result.quota_refresh,
        result.quota_ok,
        result.quota_error,
    ) = _check_quota_sdk(env, acc)

    if not result.quota_ok:
        # Fall back to kaggle CLI subprocess
        try:
            cp = _run_with_creds(["quota"], env, acc)
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("GPU") or line.startswith("TPU"):
                        parts = line.split()
                        if len(parts) >= 3:
                            resource = parts[0]
                            remaining = parts[2]
                            if resource == "GPU":
                                result.gpu_remaining = remaining
                            elif resource == "TPU":
                                result.tpu_remaining = remaining
                        if len(parts) >= 5 and not result.quota_refresh:
                            result.quota_refresh = parts[4]
                result.quota_ok = True
                result.quota_error = ""
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
