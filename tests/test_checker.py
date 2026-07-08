"""Tests for checker module."""
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import kaggle_switch.checker as checker
from kaggle_switch.checker import (
    _build_env,
    _check_quota_sdk,
    _patch_creds_expiry,
    _refresh_oauth_token,
    _require_kaggle,
    _run_kaggle,
    _run_with_creds,
    _swap_creds,
    _td,
    check_account,
    check_all_accounts,
    CheckResult,
)
from kaggle_switch.config import Account


def make_config(tmp_path, accounts_data: dict) -> dict:
    config = {"accounts": {}}
    for num, (name, config_dir) in accounts_data.items():
        config["accounts"][num] = {"name": name, "config_dir": config_dir}
    return config


def fake_subprocess_config_view(**kwargs):
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="- username: testuser\n- auth_method: LEGACY_API_KEY\n"
    )


def fake_subprocess_quota(**kwargs):
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="""Competitions    Kernels    Datasets     Disk     GPU        TPU
...              ...        ...          ...     25.87h    20.00h
GPU       25.87h  4.13h      30.00h  ...
TPU       20.00h  0.00h      20.00h  ...
"""
    )


class TestCheckAccount:
    def test_valid_account(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-testuser"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text('{"username":"testuser","key":"abc"}')

        acc = Account(number="1", name="testuser", config_dir="testuser")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [fake_subprocess_config_view(), fake_subprocess_quota()]
            result = check_account(acc)

        assert result.file_ok is True
        assert result.file_error == ""
        assert result.auth_user == "testuser"
        assert result.auth_match is True
        assert result.quota_ok is True
        assert result.gpu_remaining == "4.13h"
        assert result.tpu_remaining == "0.00h"

    def test_missing_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number="2", name="nonexistent", config_dir="nonexistent")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.return_value = fake_subprocess_config_view()
            result = check_account(acc)

        assert result.file_ok is False
        assert "no credentials" in result.file_error

    def test_auth_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-mismatch"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text('{"username":"other","key":"abc"}')

        acc = Account(number="3", name="mismatch", config_dir="mismatch")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_ok is True
        assert result.auth_user == "testuser"
        assert result.auth_match is False

    def test_kaggle_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.checker.shutil.which", lambda _: None)
        acc = Account(number="4", name="nokaggle", config_dir="nokaggle")

        result = check_account(acc)

        assert result.quota_ok is False
        assert "kaggle CLI not found on PATH" in result.quota_error

    def test_token_account_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-tokenacc"
        acc_path.mkdir(parents=True)
        (acc_path / "access_token").write_text("KGAT_7b42f4050e6bed91ef395d02a0b3dc6d\n")

        acc = Account(number="5", name="tokenacc", config_dir="tokenacc")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_ok is True

    def test_oauth_account_no_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-oauth"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text("{}")

        acc = Account(number="5", name="oauth", config_dir="oauth")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_ok is True


class TestCheckAllAccounts:
    def test_multiple_accounts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        for name in ("alpha", "beta"):
            p = tmp_path / f".kaggle-{name}"
            p.mkdir(parents=True)
            (p / "kaggle.json").write_text(json.dumps({"username": name, "key": "x"}))

        config = make_config(tmp_path, {
            "1": ("alpha", "alpha"),
            "2": ("beta", "beta"),
        })

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            results = check_all_accounts(config, max_workers=1)

        assert len(results) == 2
        assert results[0].number == "1"
        assert results[1].number == "2"
        assert all(r.quota_ok for r in results)

    def test_empty_config(self, tmp_path):
        config = {"accounts": {}}
        results = check_all_accounts(config)
        assert results == []


class TestBuildEnv:
    """_build_env must isolate the kaggle subprocess from shell env leakage."""

    def test_strips_kaggle_api_token(self, monkeypatch):
        """KAGGLE_API_TOKEN set by `kagitch switch` in parent shell must NOT
        leak into the subprocess env, otherwise kaggle CLI 2.2+ uses it for
        every account and bypasses per-account credential isolation."""
        monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_stale_token_from_switch")
        acc = Account(number="1", name="a", config_dir="a")
        env = _build_env(acc)
        assert "KAGGLE_API_TOKEN" not in env

    def test_sets_kaggle_config_dir_for_non_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KAGGLE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        acc_path = tmp_path / ".kaggle-testuser"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text('{"username":"testuser","key":"k"}')

        acc = Account(number="1", name="testuser", config_dir="testuser")
        env = _build_env(acc)
        assert env.get("KAGGLE_CONFIG_DIR") == str(acc_path)

    def test_clears_kaggle_config_dir_for_default(self, monkeypatch, tmp_path):
        """Default account must NOT inherit KAGGLE_CONFIG_DIR from shell —
        it would point at another account's directory and confuse kaggle CLI."""
        monkeypatch.setenv("KAGGLE_CONFIG_DIR", "/some/other/account/dir")
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".kaggle").mkdir(parents=True)

        acc = Account(number="1", name="default", config_dir="")
        env = _build_env(acc)
        assert "KAGGLE_CONFIG_DIR" not in env

    def test_does_not_drop_unrelated_env_vars(self, monkeypatch):
        """Sanity check: the strip only targets KAGGLE_API_TOKEN,
        other env vars must still pass through."""
        monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_x")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setenv("HOME", "/home/user")

        acc = Account(number="1", name="a", config_dir="a")
        env = _build_env(acc)
        assert env.get("PATH") == "/usr/bin:/bin"
        assert env.get("HOME") == "/home/user"
        assert "KAGGLE_API_TOKEN" not in env


class TestTD:
    def test_timedelta_conversion(self):
        """_td formats timedelta as hh:mm."""
        assert _td(timedelta(hours=1, minutes=30)) == "1h30m"
        assert _td(timedelta(minutes=5)) == "0h05m"
        assert _td(timedelta(hours=2)) == "2h00m"

    def test_td_none(self):
        """_td returns n/a for None input."""
        assert _td(None) == "n/a"


class TestTimeDeltaSerializerPatch:
    """Cover the patched _from_dict_value function body (lines 33-39)."""

    def test_none_value(self):
        """Line 33-34: None input returns None."""
        from kagglesdk.kaggle_object import TimeDeltaSerializer

        result = TimeDeltaSerializer._from_dict_value(None)
        assert result is None

    def test_whole_seconds(self):
        """Lines 35-37,39: '30s' returns timedelta(seconds=30)."""
        from kagglesdk.kaggle_object import TimeDeltaSerializer

        result = TimeDeltaSerializer._from_dict_value("30s")
        assert result == timedelta(seconds=30)

    def test_subsecond_precision(self):
        """Lines 35-39: '30.5s' parses nanos to microseconds (5//1000=0)."""
        from kagglesdk.kaggle_object import TimeDeltaSerializer

        result = TimeDeltaSerializer._from_dict_value("30.5s")
        assert result == timedelta(seconds=30)

    def test_large_nanos_value(self):
        """Lines 35-39: nanos>1000 converts to microseconds correctly."""
        from kagglesdk.kaggle_object import TimeDeltaSerializer

        result = TimeDeltaSerializer._from_dict_value("30.500000000s")
        assert result == timedelta(seconds=30, microseconds=500000)


class TestSwapCreds:
    def test_already_in_place(self, tmp_path, monkeypatch):
        """_swap_creds no-ops when source and dest resolve to same file
        (default account where acc.path == KAGGLE_DEFAULT)."""
        monkeypatch.setattr(
            "kaggle_switch.checker.KAGGLE_DEFAULT", tmp_path / ".kaggle"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.KAGGLE_DEFAULT", tmp_path / ".kaggle"
        )
        acc = Account(number="1", name="default", config_dir="")
        creds = tmp_path / ".kaggle" / "credentials.json"
        creds.parent.mkdir(parents=True)
        creds.write_text('{"some": "data"}')
        # Should not raise and should not change the file
        _swap_creds(acc)
        assert creds.read_text() == '{"some": "data"}'

    def test_source_does_not_exist_dst_exists(self, tmp_path, monkeypatch):
        """_swap_creds removes dst when src does not exist but dst does."""
        monkeypatch.setattr(
            "kaggle_switch.checker.KAGGLE_DEFAULT", tmp_path / ".kaggle"
        )
        acc = Account(number="1", name="test", config_dir="test")
        dst = tmp_path / ".kaggle" / "credentials.json"
        dst.parent.mkdir(parents=True)
        dst.write_text("old-data")
        # acc.path / "credentials.json" does not exist
        _swap_creds(acc)
        assert not dst.exists()

    def test_creates_dst_parent_and_copies(self, tmp_path, monkeypatch):
        """_swap_creds creates parent dir and copies when src exists."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(
            "kaggle_switch.checker.KAGGLE_DEFAULT", tmp_path / ".kaggle"
        )
        monkeypatch.setattr(
            "kaggle_switch.config.KAGGLE_DEFAULT", tmp_path / ".kaggle"
        )
        acc = Account(number="1", name="test", config_dir="test")
        src = tmp_path / ".kaggle-test" / "credentials.json"
        src.parent.mkdir(parents=True)
        src.write_text("cred-data")
        _swap_creds(acc)
        dst = tmp_path / ".kaggle" / "credentials.json"
        assert dst.read_text() == "cred-data"


class TestPatchCredsExpiry:
    def test_invalid_json_no_error(self, tmp_path):
        """_patch_creds_expiry silently handles JSON decode errors."""
        bad = tmp_path / "credentials.json"
        bad.write_text("{not valid json}")
        # Should not raise
        _patch_creds_expiry(bad)

    def test_naive_expiration_patched(self, tmp_path):
        """_patch_creds_expiry adds timezone offset to naive timestamp."""
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"access_token_expiration": "2026-07-09T12:00:00"})
        )
        _patch_creds_expiry(creds)
        data = json.loads(creds.read_text())
        assert "+00:00" in data["access_token_expiration"]

    def test_aware_expiration_untouched(self, tmp_path):
        """_patch_creds_expiry leaves already-aware timestamps alone."""
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"access_token_expiration": "2026-07-09T12:00:00+00:00"})
        )
        _patch_creds_expiry(creds)
        data = json.loads(creds.read_text())
        assert data["access_token_expiration"] == "2026-07-09T12:00:00+00:00"

    def test_utc_z_suffix_untouched(self, tmp_path):
        """_patch_creds_expiry leaves Z-suffix timestamps alone."""
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"access_token_expiration": "2026-07-09T12:00:00Z"})
        )
        _patch_creds_expiry(creds)
        data = json.loads(creds.read_text())
        assert data["access_token_expiration"] == "2026-07-09T12:00:00Z"


class TestCheckAccount:
    # (existing tests are above — these are additional tests)

    def test_json_decode_error(self, tmp_path, monkeypatch):
        """check_account handles unparseable kaggle.json gracefully."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-badjson"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text("{bad json}")

        acc = Account(number="7", name="badjson", config_dir="badjson")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_ok is False
        # Should get a JSON decode error message
        assert result.file_error != ""

    def test_missing_username_key_fields(self, tmp_path, monkeypatch):
        """check_account detects kaggle.json missing username/key."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-nofields"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text(
            json.dumps({"not_username": "x", "not_key": "y"})
        )

        acc = Account(number="8", name="nofields", config_dir="nofields")

        with patch("kaggle_switch.checker._run_kaggle") as mock:
            mock.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_error == "missing username/key fields"

    def test_config_view_timeout(self, tmp_path, monkeypatch):
        """check_account handles TimeoutExpired from config view."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-timeout"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text(
            json.dumps({"username": "u", "key": "k"})
        )

        acc = Account(number="9", name="timeout", config_dir="timeout")

        with patch(
            "kaggle_switch.checker._run_with_creds"
        ) as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="kaggle", timeout=15)
            result = check_account(acc)

        assert result.quota_error != ""
        assert result.auth_match is False

    def test_quota_fallback_timeout(self, tmp_path, monkeypatch):
        """check_account handles TimeoutExpired from quota fallback."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-quotatimeout"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text(
            json.dumps({"username": "u", "key": "k"})
        )

        acc = Account(number="10", name="quotatimeout", config_dir="quotatimeout")

        # First call (config view) succeeds, quota SDK returns error,
        # then quota fallback raises TimeoutExpired
        with patch("kaggle_switch.checker._run_with_creds") as mock_run, patch(
            "kaggle_switch.checker._check_quota_sdk"
        ) as mock_sdk:
            mock_run.side_effect = [
                fake_subprocess_config_view(),
                subprocess.TimeoutExpired(cmd="kaggle", timeout=15),
            ]
            mock_sdk.return_value = ("", "", "", False, "sdk failed")
            result = check_account(acc)

        assert result.quota_error != ""
        assert result.file_ok is True

    def test_quota_fallback_stderr(self, tmp_path, monkeypatch):
        """check_account captures stderr from failed quota fallback (line 417)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-quotaerr"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text(
            json.dumps({"username": "u", "key": "k"})
        )
        acc = Account(number="11", name="quotaerr", config_dir="quotaerr")

        with patch("kaggle_switch.checker._run_with_creds") as mock_run, patch(
            "kaggle_switch.checker._check_quota_sdk"
        ) as mock_sdk:
            # Config view succeeds, quota CLI returns non-zero with stderr
            mock_run.side_effect = [
                fake_subprocess_config_view(),
                subprocess.CompletedProcess(
                    args=[], returncode=1, stderr="too many requests"
                ),
            ]
            mock_sdk.return_value = ("", "", "", False, "sdk failed")
            result = check_account(acc)

        assert result.quota_error != ""
        assert "too many requests" in result.quota_error

    def test_oauth_creds_only_auth_match(self, tmp_path, monkeypatch):
        """check_account sets auth_match for OAuth credits with auth_method (lines 380-381)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-oauthmatch"
        acc_path.mkdir(parents=True)
        # Only credentials.json — no kaggle.json
        (acc_path / "credentials.json").write_text(
            json.dumps({"access_token": "KGAT_xxxx"})
        )
        acc = Account(number="12", name="oauthmatch", config_dir="oauthmatch")

        with patch("kaggle_switch.checker._run_with_creds") as mock_run, patch(
            "kaggle_switch.checker._check_quota_sdk"
        ) as mock_sdk:
            mock_run.side_effect = [
                fake_subprocess_config_view(),
                fake_subprocess_quota(),
            ]
            mock_sdk.return_value = ("25.0h", "", "", True, "")
            result = check_account(acc)

        assert result.file_ok is True
        assert result.auth_match is True


class TestCheckAllAccounts:
    def test_default_config(self, monkeypatch):
        """check_all_accounts loads config when None is passed."""
        monkeypatch.setattr(
            "kaggle_switch.checker.load_config",
            lambda: {"accounts": {}},
        )
        results = check_all_accounts(config=None)
        assert results == []

    def test_with_accounts_returns_results(self, tmp_path, monkeypatch):
        """Covers ThreadPoolExecutor result collection (line 437)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", tmp_path / ".kaggle")
        monkeypatch.setattr("kaggle_switch.checker._HAS_SDK", False)
        acc_dir = tmp_path / ".kaggle-testacct"
        acc_dir.mkdir(parents=True)
        (acc_dir / "kaggle.json").write_text('{"username":"t","key":"k"}')
        config_obj = {
            "accounts": {"1": {"name": "testacct", "config_dir": "testacct"}}
        }
        with patch("kaggle_switch.checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="ok")
            results = check_all_accounts(config=config_obj, max_workers=1)
        assert len(results) == 1
        assert results[0].name == "testacct"


class TestCheckerModuleImport:
    """Cover kagglesdk import failure path (lines 43-44)."""

    def test_hassdk_defined(self):
        assert hasattr(checker, "_HAS_SDK")

    def test_import_without_sdk_sets_has_sdk_false(self):
        original_import = __import__

        def fail_kagglesdk_import(name, *args, **kwargs):
            if name.startswith("kagglesdk"):
                raise ImportError("missing sdk")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_kagglesdk_import):
            import importlib

            mod = importlib.reload(checker)

        assert mod._HAS_SDK is False

        import importlib

        importlib.reload(checker)


class TestRefreshOAuthToken:
    def test_no_creds_file(self, tmp_path):
        """_refresh_oauth_token returns None when credentials.json missing."""
        acc = Account(number="1", name="test", config_dir="test")
        # Override path to point at tmp_path with no credentials.json
        acc_path = tmp_path / ".kaggle-test"
        acc_path.mkdir(parents=True)
        with patch.object(Account, "path", acc_path):
            result = _refresh_oauth_token(acc)
        assert result is None

    def test_bad_json(self, tmp_path):
        """_refresh_oauth_token returns None on JSON decode error."""
        acc = Account(number="1", name="test", config_dir="test")
        acc_path = tmp_path / ".kaggle-test"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text("{bad}")
        with patch.object(Account, "path", acc_path):
            result = _refresh_oauth_token(acc)
        assert result is None

    def test_no_refresh_token(self, tmp_path):
        """_refresh_oauth_token returns None when refresh_token missing."""
        acc = Account(number="1", name="test", config_dir="test")
        acc_path = tmp_path / ".kaggle-test"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text(
            json.dumps({"access_token": "abc"})
        )
        with patch.object(Account, "path", acc_path):
            result = _refresh_oauth_token(acc)
        assert result is None

    def test_http_error(self, tmp_path):
        """_refresh_oauth_token returns None on non-200 response."""
        acc = Account(number="1", name="test", config_dir="test")
        acc_path = tmp_path / ".kaggle-test"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text(
            json.dumps({"refresh_token": "rt1"})
        )
        with patch.object(Account, "path", acc_path), patch(
            "requests.post"
        ) as mock_post:
            mock_post.return_value.status_code = 400
            result = _refresh_oauth_token(acc)
        assert result is None

    def test_success(self, tmp_path):
        """_refresh_oauth_token returns token data on success."""
        acc = Account(number="1", name="test", config_dir="test")
        acc_path = tmp_path / ".kaggle-test"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text(
            json.dumps({"refresh_token": "rt1"})
        )
        with patch.object(Account, "path", acc_path), patch(
            "requests.post"
        ) as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "KGAT_new_token_123456",
                "refresh_token": "new_rt",
                "expires_in": 10800,
            }
            result = _refresh_oauth_token(acc)
        assert result is not None
        assert result[0] == "KGAT_new_token_123456"
        assert result[1] == "new_rt"
        assert result[2] == 10800

    def test_short_token_rejected(self, tmp_path):
        """_refresh_oauth_token rejects token shorter than 21 chars (line 206)."""
        acc = Account(number="1", name="test", config_dir="test")
        acc_path = tmp_path / ".kaggle-test"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text(
            json.dumps({"refresh_token": "rt1"})
        )
        with patch.object(Account, "path", acc_path), patch(
            "requests.post"
        ) as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "short",
                "refresh_token": "new_rt",
                "expires_in": 10800,
            }
            result = _refresh_oauth_token(acc)
        assert result is None

    def test_network_error_returns_none(self, tmp_path):
        """_refresh_oauth_token catches requests.post exception (lines 210-211)."""
        acc = Account(number="1", name="test", config_dir="test")
        acc_path = tmp_path / ".kaggle-test"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text(
            json.dumps({"refresh_token": "rt1"})
        )
        with patch.object(Account, "path", acc_path), patch(
            "requests.post", side_effect=ConnectionError("network down")
        ):
            result = _refresh_oauth_token(acc)
        assert result is None


class TestCheckQuotaSDK:
    def test_no_sdk(self, monkeypatch):
        """_check_quota_sdk returns error when kagglesdk is unavailable."""
        monkeypatch.setattr(
            "kaggle_switch.checker._HAS_SDK", False
        )
        acc = Account(number="1", name="a", config_dir="a")
        result = _check_quota_sdk({}, acc)
        assert result == ("", "", "", False, "kagglesdk not available")


class TestRunWithCreds:
    def test_cleanup_after_swap_creates_backup(self, tmp_path, monkeypatch):
        """_run_with_creds cleans up credentials.json created during swap."""
        monkeypatch.setattr(
            "kaggle_switch.checker.KAGGLE_DEFAULT", tmp_path / ".kaggle"
        )
        monkeypatch.setattr(
            "kaggle_switch.checker._run_kaggle",
            lambda cmd, env, timeout=15: subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok"
            ),
        )
        monkeypatch.setattr(
            "kaggle_switch.checker._patch_creds_expiry", lambda path=None: None
        )

        acc = Account(number="1", name="test", config_dir="test")
        # Create source credentials.json so _swap_creds copies it to
        # KAGGLE_DEFAULT / "credentials.json" (which did NOT exist before)
        src = tmp_path / ".kaggle-test" / "credentials.json"
        src.parent.mkdir(parents=True)
        src.write_text("{}")

        # Backup path does not exist before — after swap it will exist,
        # and _run_with_creds must clean it up
        dst = tmp_path / ".kaggle" / "credentials.json"
        assert not dst.exists()

        _run_with_creds(["config", "view"], {}, acc)

        # Backup must be cleaned up in finally
        assert not dst.exists()

    def test_restores_backup_when_present(self, tmp_path, monkeypatch):
        """_run_with_creds restores original credentials.json after run."""
        monkeypatch.setattr(
            "kaggle_switch.checker.KAGGLE_DEFAULT", tmp_path / ".kaggle"
        )
        monkeypatch.setattr(
            "kaggle_switch.checker._run_kaggle",
            lambda cmd, env, timeout=15: subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok"
            ),
        )
        monkeypatch.setattr(
            "kaggle_switch.checker._patch_creds_expiry", lambda path=None: None
        )

        acc = Account(number="1", name="test", config_dir="test")
        # Pre-existing backup
        dst = tmp_path / ".kaggle" / "credentials.json"
        dst.parent.mkdir(parents=True)
        dst.write_text("original")

        # Source credentials.json — swap will overwrite the backup
        src = tmp_path / ".kaggle-test" / "credentials.json"
        src.parent.mkdir(parents=True)
        src.write_text("new-data")

        _run_with_creds(["config", "view"], {}, acc)

        # Backup must be restored
        assert dst.read_text() == "original"


class TestRequireKaggle:
    def test_kaggle_found(self, monkeypatch):
        """_require_kaggle returns None when kaggle is on PATH."""
        monkeypatch.setattr("kaggle_switch.checker.shutil.which", lambda _: "/usr/bin/kaggle")
        assert _require_kaggle() is None

    def test_kaggle_not_found(self, monkeypatch):
        """_require_kaggle returns error string when kaggle is missing."""
        monkeypatch.setattr("kaggle_switch.checker.shutil.which", lambda _: None)
        err = _require_kaggle()
        assert err is not None
        assert "kaggle CLI not found" in err


class TestRunKaggle:
    def test_delegates_to_subprocess(self, monkeypatch):
        """_run_kaggle calls subprocess.run with kaggle prefix."""
        from unittest.mock import MagicMock

        mock = MagicMock(return_value=subprocess.CompletedProcess([], 0))
        monkeypatch.setattr(subprocess, "run", mock)
        result = _run_kaggle(["quota"], {"ENV": "val"})
        mock.assert_called_once_with(
            ["kaggle", "quota"],
            capture_output=True,
            text=True,
            timeout=15,
            env={"ENV": "val"},
        )
        assert result.returncode == 0

    def test_custom_timeout(self, monkeypatch):
        """_run_kaggle passes custom timeout through."""
        from unittest.mock import MagicMock

        mock = MagicMock(return_value=subprocess.CompletedProcess([], 0))
        monkeypatch.setattr(subprocess, "run", mock)
        _run_kaggle(["foo"], {"ENV": "val"}, timeout=42)
        assert mock.call_args[1]["timeout"] == 42

    def test_windows_creationflags(self, monkeypatch):
        """Line 149: CREATE_NO_WINDOW flag added on Windows."""
        from unittest.mock import MagicMock

        mock = MagicMock(return_value=subprocess.CompletedProcess([], 0))
        monkeypatch.setattr(subprocess, "run", mock)
        monkeypatch.setattr("sys.platform", "win32")
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
        result = _run_kaggle(["quota"], {"ENV": "val"})
        assert mock.call_args[1]["creationflags"] == 0x08000000
        assert result.returncode == 0


class TestCheckAccountExtended:
    def test_kaggle_cli_not_found(self, tmp_path, monkeypatch):
        """check_account sets both error fields when kaggle CLI missing (lines 332-334)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.checker.shutil.which", lambda _: None)
        acc_path = tmp_path / ".kaggle-nokaggle"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text(
            json.dumps({"username": "u", "key": "k"})
        )
        acc = Account(number="20", name="nokaggle", config_dir="nokaggle")
        result = check_account(acc)
        assert "kaggle CLI not found" in result.quota_error
        assert "kaggle CLI not found" in result.file_error

    def test_access_token_file_cred(self, tmp_path, monkeypatch):
        """check_account handles access_token file (lines 351-353)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.checker.shutil.which", lambda _: "/usr/bin/kaggle")
        acc_path = tmp_path / ".kaggle-atoken"
        acc_path.mkdir(parents=True)
        (acc_path / "access_token").write_text("KGAT_xxxxxx")
        acc = Account(number="21", name="atoken", config_dir="atoken")

        with patch("kaggle_switch.checker._run_with_creds") as mock_run:
            mock_run.side_effect = [
                subprocess.TimeoutExpired(cmd="kaggle", timeout=15),
                fake_subprocess_quota(),
            ]
            result = check_account(acc)

        assert result.file_ok is True
        assert result.auth_user == "atoken"
        assert result.file_error == ""

    def test_no_credentials_found(self, tmp_path, monkeypatch):
        """check_account reports error when no credential file exists (line 358)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc_path = tmp_path / ".kaggle-nocreds"
        acc_path.mkdir(parents=True)
        # No kaggle.json, access_token, or credentials.json
        acc = Account(number="22", name="nocreds", config_dir="nocreds")
        result = check_account(acc)
        assert result.file_ok is False
        assert result.file_error == "no credentials found"

    def test_config_view_returns_nonzero(self, tmp_path, monkeypatch):
        """check_account sets auth_match=False when config view fails (line 373)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.checker.shutil.which", lambda _: "/usr/bin/kaggle")
        acc_path = tmp_path / ".kaggle-configfail"
        acc_path.mkdir(parents=True)
        (acc_path / "kaggle.json").write_text(
            json.dumps({"username": "u", "key": "k"})
        )
        acc = Account(number="23", name="configfail", config_dir="configfail")

        with patch("kaggle_switch.checker._run_with_creds") as mock_run, patch(
            "kaggle_switch.checker._check_quota_sdk"
        ) as mock_sdk:
            mock_run.side_effect = [
                subprocess.CompletedProcess([], returncode=1, stderr="error"),
                fake_subprocess_quota(),
            ]
            mock_sdk.return_value = ("", "", "", True, "")
            result = check_account(acc)

        assert result.file_ok is True
        assert result.auth_match is False


class TestRunWithCredsExtended:
    def test_swap_cleanup_without_backup(self, tmp_path, monkeypatch):
        """_run_with_creds removes backup file when no original existed (line 119)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch
        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", tmp_path / ".kaggle")
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", tmp_path / ".kaggle")

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        acc_path = tmp_path / ".kaggle-acc25"
        acc_path.mkdir(parents=True)
        (acc_path / "credentials.json").write_text(
            json.dumps({"access_token": "KGAT_xxxx"})
        )
        acc = Account(number="25", name="acc25", config_dir="acc25")

        env = _build_env(acc)
        # Mock subprocess.run so we don't invoke real kaggle
        with patch("kaggle_switch.checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="ok")
            _run_with_creds(["config", "view"], env, acc)

        # The backup file should have been cleaned up
        assert not (kd / "credentials.json").exists()


class TestCheckQuotaSDKFullFlow:
    def test_oauth_token_creates_kaggle_client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch
        from unittest.mock import MagicMock

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        (kd / "credentials.json").write_text(
            json.dumps({
                "access_token": "KGAT_test_token_12345abc",
                "refresh_token": "rt_abc",
                "access_token_expiration": (
                    datetime.now() + timedelta(hours=1)
                ).isoformat(),
            })
        )

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)
        m.setattr("kaggle_switch.checker._swap_creds", lambda _: None)
        m.setattr("kaggle_switch.checker._patch_creds_expiry", lambda: None)

        mock_client = MagicMock()
        checker.KaggleClient = MagicMock(return_value=mock_client)

        class MockTD:
            def __init__(self, secs):
                self._secs = secs
            def total_seconds(self):
                return self._secs
            def __sub__(self, other):
                if hasattr(other, 'total_seconds'):
                    return timedelta(seconds=self._secs - other.total_seconds())
                return timedelta(seconds=self._secs - other)

        class MockGPU:
            total_time_allowed = MockTD(7200)
            time_used = MockTD(1800)

        resp = MagicMock()
        resp.gpu_quota = MockGPU()
        resp.tpu_quota = None
        resp.quota_refresh_time = datetime.fromisoformat("2026-07-10T00:00:00+00:00")
        mock_client.kernels.kernels_api_client.get_accelerator_quota_statistics.return_value = resp

        acc = Account(number="30", name="sdk-oauth", config_dir="sdk-oauth")
        gpu, tpu, refresh, ok, err = _check_quota_sdk({}, acc)

        assert ok is True, f"oauth token flow failed: err={err}"
        assert gpu == "1.50h"
        assert tpu == "n/a"
        assert refresh == "2026-07-10T00:00:00+00:00"

    def test_legacy_kaggle_json_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch
        from unittest.mock import MagicMock

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        (kd / "kaggle.json").write_text(
            json.dumps({"username": "testuser", "key": "testkey123"})
        )

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)
        m.setattr("kaggle_switch.checker._swap_creds", lambda _: None)
        m.setattr("kaggle_switch.checker._patch_creds_expiry", lambda: None)

        mock_client = MagicMock()
        checker.KaggleClient = MagicMock(return_value=mock_client)

        class MockTD:
            def __init__(self, secs):
                self._secs = secs
            def total_seconds(self):
                return self._secs
            def __sub__(self, other):
                if hasattr(other, 'total_seconds'):
                    return timedelta(seconds=self._secs - other.total_seconds())
                return timedelta(seconds=self._secs - other)

        class MockGPU:
            total_time_allowed = MockTD(3600)
            time_used = MockTD(0)

        resp = MagicMock()
        resp.gpu_quota = MockGPU()
        resp.tpu_quota = None
        resp.quota_refresh_time = None
        mock_client.kernels.kernels_api_client.get_accelerator_quota_statistics.return_value = resp

        acc = Account(number="31", name="sdk-legacy", config_dir="sdk-legacy")
        gpu, tpu, refresh, ok, err = _check_quota_sdk({}, acc)

        assert ok is True, f"legacy flow failed: err={err}"
        assert gpu == "1.00h"
        assert refresh == ""

    def test_oauth_token_expired_refreshes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch
        from unittest.mock import MagicMock, patch as u_patch

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        (kd / "credentials.json").write_text(
            json.dumps({
                "access_token": "KGAT_expired",
                "refresh_token": "rt_expired",
                "access_token_expiration": (
                    datetime.now() - timedelta(hours=1)
                ).isoformat(),
            })
        )

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)
        m.setattr("kaggle_switch.checker._swap_creds", lambda _: None)
        m.setattr("kaggle_switch.checker._patch_creds_expiry", lambda: None)

        mock_client = MagicMock()
        checker.KaggleClient = MagicMock(return_value=mock_client)

        class MockTD:
            def __init__(self, secs):
                self._secs = secs
            def total_seconds(self):
                return self._secs
            def __sub__(self, other):
                if hasattr(other, 'total_seconds'):
                    return timedelta(seconds=self._secs - other.total_seconds())
                return timedelta(seconds=self._secs - other)

        resp = MagicMock()
        resp.gpu_quota = None
        resp.tpu_quota = None
        resp.quota_refresh_time = None
        mock_client.kernels.kernels_api_client.get_accelerator_quota_statistics.return_value = resp

        acc = Account(number="32", name="sdk-expired", config_dir="sdk-expired")
        with u_patch("kaggle_switch.checker._refresh_oauth_token") as mock_refresh:
            mock_refresh.return_value = ("KGAT_refreshed_token_val", "rt_new", 7200)
            gpu, tpu, refresh, ok, err = _check_quota_sdk({}, acc)

        assert ok is True, f"expired token flow failed: err={err}"
        assert gpu == "n/a"
        assert tpu == "n/a"
        mock_refresh.assert_called_once()

    def test_no_credentials_returns_error(self, tmp_path, monkeypatch):
        """_check_quota_sdk returns error when no credentials exist (line 287)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        # No credentials.json or kaggle.json at all

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)

        acc = Account(number="33", name="sdk-nocreds", config_dir="sdk-nocreds")
        _, _, _, ok, err = _check_quota_sdk({}, acc)
        assert ok is False
        assert "no credentials found" in err

    def test_malformed_expiry_timestamp(self, tmp_path, monkeypatch):
        """Bad access_token_expiration is treated as expired and triggers refresh (lines 251-252)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch
        from unittest.mock import MagicMock, patch as u_patch

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        (kd / "credentials.json").write_text(
            json.dumps({
                "access_token": "KGAT_bad_exp",
                "refresh_token": "rt_bad_exp",
                "access_token_expiration": "not-a-valid-datetime",
            })
        )

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)
        m.setattr("kaggle_switch.checker._swap_creds", lambda _: None)
        m.setattr("kaggle_switch.checker._patch_creds_expiry", lambda: None)

        mock_client = MagicMock()
        checker.KaggleClient = MagicMock(return_value=mock_client)

        resp = MagicMock()
        resp.gpu_quota = None
        resp.tpu_quota = None
        resp.quota_refresh_time = None
        mock_client.kernels.kernels_api_client.get_accelerator_quota_statistics.return_value = resp

        acc = Account(number="34", name="sdk-bad-exp", config_dir="sdk-bad-exp")
        with u_patch("kaggle_switch.checker._refresh_oauth_token") as mock_refresh:
            mock_refresh.return_value = ("KGAT_refreshed", "rt_new", 7200)
            gpu, tpu, refresh, ok, err = _check_quota_sdk({}, acc)

        assert ok is True, f"malformed expiry should treat as expired: err={err}"
        assert gpu == "n/a"
        mock_refresh.assert_called_once()

    def test_corrupted_kaggle_json(self, tmp_path, monkeypatch):
        """Corrupted kaggle.json falls through to no-credentials error (lines 283-284)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        (kd / "kaggle.json").write_text("{{{ not valid json }}}")

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)

        acc = Account(number="35", name="sdk-bad-kaggle", config_dir="sdk-bad-kaggle")
        _, _, _, ok, err = _check_quota_sdk({}, acc)
        assert ok is False
        assert "no credentials found" in err

    def test_tpu_quota_calculation(self, tmp_path, monkeypatch):
        """TPU quota is calculated when tpu_quota is not None (lines 300-301)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch
        from unittest.mock import MagicMock

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        (kd / "kaggle.json").write_text(
            json.dumps({"username": "testuser", "key": "testkey123"})
        )

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)
        m.setattr("kaggle_switch.checker._swap_creds", lambda _: None)
        m.setattr("kaggle_switch.checker._patch_creds_expiry", lambda: None)

        mock_client = MagicMock()
        checker.KaggleClient = MagicMock(return_value=mock_client)

        class MockTD:
            def __init__(self, secs):
                self._secs = secs
            def total_seconds(self):
                return self._secs
            def __sub__(self, other):
                if hasattr(other, 'total_seconds'):
                    return timedelta(seconds=self._secs - other.total_seconds())
                return timedelta(seconds=self._secs - other)

        class MockQuota:
            total_time_allowed = MockTD(7200)
            time_used = MockTD(900)

        resp = MagicMock()
        resp.gpu_quota = None
        resp.tpu_quota = MockQuota()
        resp.quota_refresh_time = None
        mock_client.kernels.kernels_api_client.get_accelerator_quota_statistics.return_value = resp

        acc = Account(number="36", name="sdk-tpu", config_dir="sdk-tpu")
        gpu, tpu, refresh, ok, err = _check_quota_sdk({}, acc)

        assert ok is True, f"tpu flow failed: err={err}"
        assert gpu == "n/a"
        assert tpu == "1.75h"

    def test_corrupted_credentials_json(self, tmp_path, monkeypatch):
        """Corrupted credentials.json triggers inner except (lines 269-270)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        (kd / "credentials.json").write_text("{{{ bad json }}}")

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)
        m.setattr("kaggle_switch.checker._swap_creds", lambda _: None)
        m.setattr("kaggle_switch.checker._patch_creds_expiry", lambda: None)

        acc = Account(number="37", name="sdk-bad-creds", config_dir="sdk-bad-creds")
        _, _, _, ok, err = _check_quota_sdk({}, acc)
        assert ok is False
        assert "no credentials found" in err

    def test_outer_exception_caught(self, tmp_path, monkeypatch):
        """Exception from KaggleClient is caught by outer handler (lines 310-314)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch
        from unittest.mock import MagicMock

        kd = tmp_path / ".kaggle"
        kd.mkdir()
        (kd / "credentials.json").write_text(
            json.dumps({
                "access_token": "KGAT_working",
                "access_token_expiration": (
                    datetime.now() + timedelta(hours=1)
                ).isoformat(),
            })
        )

        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)
        m.setattr("kaggle_switch.checker._swap_creds", lambda _: None)
        m.setattr("kaggle_switch.checker._patch_creds_expiry", lambda: None)

        mock_client = MagicMock()
        checker.KaggleClient = MagicMock(return_value=mock_client)

        mock_client.kernels.kernels_api_client.get_accelerator_quota_statistics.side_effect = RuntimeError("A" * 250)

        acc = Account(number="38", name="sdk-explode", config_dir="sdk-explode")
        _, _, _, ok, err = _check_quota_sdk({}, acc)
        assert ok is False
        assert len(err) == 200
        # Also test with a short error msg to cover the non-truncation branch
        mock_client2 = MagicMock()
        checker.KaggleClient = MagicMock(return_value=mock_client2)
        mock_client2.kernels.kernels_api_client.get_accelerator_quota_statistics.side_effect = RuntimeError("boom")
        _, _, _, ok2, err2 = _check_quota_sdk({}, acc)
        assert ok2 is False
        assert err2 == "boom"

    def test_backup_cleanup_after_swap(self, tmp_path, monkeypatch):
        """finally block cleans up swapped creds when none existed before (line 319)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m = monkeypatch
        from unittest.mock import MagicMock

        kd = tmp_path / ".kaggle"
        kd.mkdir()

        # Account directory with credentials.json (source for _swap_creds)
        acc_dir = tmp_path / ".kaggle-sdk-line319"
        acc_dir.mkdir()
        (acc_dir / "credentials.json").write_text(
            json.dumps({
                "access_token": "KGAT_cleanup",
                "access_token_expiration": (
                    datetime.now() + timedelta(hours=1)
                ).isoformat(),
            })
        )

        # No credentials.json at KAGGLE_DEFAULT initially (so backup_data = None)
        m.setattr("kaggle_switch.config.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker.KAGGLE_DEFAULT", kd)
        m.setattr("kaggle_switch.checker._HAS_SDK", True)
        # DO NOT mock _swap_creds -- let it copy the file
        m.setattr("kaggle_switch.checker._patch_creds_expiry", lambda: None)

        mock_client = MagicMock()
        checker.KaggleClient = MagicMock(return_value=mock_client)

        class MockTD:
            def __init__(self, secs):
                self._secs = secs
            def total_seconds(self):
                return self._secs
            def __sub__(self, other):
                if hasattr(other, 'total_seconds'):
                    return timedelta(seconds=self._secs - other.total_seconds())
                return timedelta(seconds=self._secs - other)

        class MockGPU:
            total_time_allowed = MockTD(3600)
            time_used = MockTD(0)

        resp = MagicMock()
        resp.gpu_quota = MockGPU()
        resp.tpu_quota = None
        resp.quota_refresh_time = None
        mock_client.kernels.kernels_api_client.get_accelerator_quota_statistics.return_value = resp

        acc = Account(number="39", name="sdk-line319", config_dir="sdk-line319")
        gpu, tpu, refresh, ok, err = _check_quota_sdk({}, acc)

        assert ok is True, f"cleanup flow failed: err={err}"
        assert gpu == "1.00h"
        # The swapped-in credentials.json should be removed by finally block
        assert not (kd / "credentials.json").exists()
