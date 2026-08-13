"""Tests for kernel command module."""
from __future__ import annotations

import json
import re
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from kaggle_switch.commands import kernel as kn
from kaggle_switch.config import Account


# ── _auto_patch_metadata ────────────────────────────────────────


class TestAutoPatchMetadata:
    def test_no_file_returns_none(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        assert kn._auto_patch_metadata(target, "auser") is None

    def test_is_directory_appends_filename(self, tmp_path):
        sub = tmp_path / "mysub"
        sub.mkdir()
        file = sub / "kernel-metadata.json"
        assert not file.exists()
        assert kn._auto_patch_metadata(sub, "auser") is None

    def test_dir_with_nested_file_patches(self, tmp_path):
        sub = tmp_path / "mysub"
        sub.mkdir()
        file = sub / "kernel-metadata.json"
        file.write_text(json.dumps({"id": "olduser/my-kernel"}))
        result = kn._auto_patch_metadata(sub, "newuser")
        assert result is not None
        assert "olduser" in result and "newuser" in result
        assert json.loads(file.read_text())["id"] == "newuser/my-kernel"

    def test_bad_json_returns_none(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text("not-json")
        assert kn._auto_patch_metadata(target, "auser") is None

    def test_oserror_on_read_returns_none(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text("{}")
        with patch.object(Path, "read_text", side_effect=OSError):
            assert kn._auto_patch_metadata(target, "auser") is None

    def test_missing_id_returns_none(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text(json.dumps({"title": "no id here"}))
        assert kn._auto_patch_metadata(target, "auser") is None

    def test_id_without_slash_returns_none(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text(json.dumps({"id": "justname"}))
        assert kn._auto_patch_metadata(target, "auser") is None

    def test_same_user_returns_none(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text(json.dumps({"id": "auser/my-kernel"}))
        assert kn._auto_patch_metadata(target, "auser") is None

    def test_different_user_returns_patch_line(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text(json.dumps({"id": "olduser/my-kernel"}))
        result = kn._auto_patch_metadata(target, "newuser")
        assert result is not None
        assert "olduser" in result and "newuser" in result
        assert json.loads(target.read_text())["id"] == "newuser/my-kernel"

    def test_oserror_on_write_returns_none(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text(json.dumps({"id": "olduser/my-kernel"}))
        with patch.object(Path, "write_text", side_effect=OSError):
            result = kn._auto_patch_metadata(target, "newuser")
        assert result is None

    def test_oserror_on_write_no_side_effect_oserror(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text(json.dumps({"id": "olduser/my-kernel"}))
        with patch.object(Path, "write_text", side_effect=OSError):
            result = kn._auto_patch_metadata(target, "newuser")
        assert result is None


# ── _active_username edge cases ────────────────────────────────


class TestActiveUsername:
    def test_no_active_account_reads_default_kaggle_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config: dict = {"accounts": {}}
        assert kn._active_username(config) is None

    def test_credentials_json_decode_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config: dict = {
            "accounts": {
                "1": {"name": "acc1", "config_dir": str(tmp_path / ".kaggle-acc1")}
            }
        }
        acc_dir = tmp_path / ".kaggle-acc1"
        acc_dir.mkdir(parents=True)
        creds = acc_dir / "credentials.json"
        creds.write_text("bad-json")
        result = kn._active_username(config)
        assert result is None

    def test_kaggle_json_decode_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config: dict = {
            "accounts": {
                "1": {"name": "acc1", "config_dir": str(tmp_path / ".kaggle-acc1")}
            }
        }
        acc_dir = tmp_path / ".kaggle-acc1"
        acc_dir.mkdir(parents=True)
        kj = acc_dir / "kaggle.json"
        kj.write_text("bad-json")
        result = kn._active_username(config)
        assert result is None

    def test_both_files_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config: dict = {
            "accounts": {
                "1": {"name": "acc1", "config_dir": str(tmp_path / ".kaggle-acc1")}
            }
        }
        acc_dir = tmp_path / ".kaggle-acc1"
        acc_dir.mkdir(parents=True)
        result = kn._active_username(config)
        assert result is None

    def test_credentials_oserror(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config: dict = {
            "accounts": {
                "1": {"name": "acc1", "config_dir": str(tmp_path / ".kaggle-acc1")}
            }
        }
        acc_dir = tmp_path / ".kaggle-acc1"
        acc_dir.mkdir(parents=True)
        creds = acc_dir / "credentials.json"
        creds.write_text('{"username": "testuser"}')
        with patch.object(Path, "read_text", side_effect=OSError):
            result = kn._active_username(config)
        assert result is None

    def test_kaggle_oserror(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config: dict = {
            "accounts": {
                "1": {"name": "acc1", "config_dir": str(tmp_path / ".kaggle-acc1")}
            }
        }
        acc_dir = tmp_path / ".kaggle-acc1"
        acc_dir.mkdir(parents=True)
        kj = acc_dir / "kaggle.json"
        kj.write_text('{"username": "testuser"}')
        with patch.object(Path, "read_text", side_effect=OSError):
            result = kn._active_username(config)
        assert result is None

    def test_credentials_happy_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config: dict = {
            "active": 1,
            "accounts": {
                "1": {"name": "acc1", "config_dir": "acc1"}
            },
        }
        acc_dir = tmp_path / ".kaggle-acc1"
        acc_dir.mkdir(parents=True)
        creds = acc_dir / "credentials.json"
        creds.write_text('{"username": "testuser"}')
        result = kn._active_username(config)
        assert result == "testuser"

    def test_kaggle_json_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config: dict = {
            "active": 1,
            "accounts": {
                "1": {"name": "acc1", "config_dir": "acc1"}
            },
        }
        acc_dir = tmp_path / ".kaggle-acc1"
        acc_dir.mkdir(parents=True)
        kj = acc_dir / "kaggle.json"
        kj.write_text('{"username": "kjuser"}')
        result = kn._active_username(config)
        assert result == "kjuser"

    def test_no_active_account_with_default_kaggle(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        default = tmp_path / ".kaggle"
        default.mkdir(parents=True)
        creds = default / "credentials.json"
        creds.write_text('{"username": "defaultuser"}')
        config: dict = {"accounts": {}}
        result = kn._active_username(config)
        assert result == "defaultuser"

    def test_current_active_none_uses_default_bad_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel.current_active", lambda config: None)
        default = tmp_path / ".kaggle"
        default.mkdir(parents=True)
        (default / "credentials.json").write_text("bad-json")
        config: dict = {"accounts": {"1": {"name": "acc1", "config_dir": "acc1"}}}
        result = kn._active_username(config)
        assert result is None

    def test_current_active_none_uses_default_kaggle_json_oserror(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel.current_active", lambda config: None)
        default = tmp_path / ".kaggle"
        default.mkdir(parents=True)
        (default / "kaggle.json").write_text('{"username": "defaultuser"}')
        config: dict = {"accounts": {"1": {"name": "acc1", "config_dir": "acc1"}}}
        with patch.object(Path, "read_text", side_effect=OSError):
            result = kn._active_username(config)
        assert result is None


# ── _parse_logs_args ────────────────────────────────────────────


class TestParseLogsArgs:
    def test_empty(self):
        pos, follow, limit, stream, progress, browse, errors_only, summary_view, no_group = kn._parse_logs_args([])
        assert pos == []
        assert follow is False
        assert limit == 0
        assert stream is None
        assert progress is False
        assert browse is False
        assert errors_only is False
        assert summary_view is False
        assert no_group is False

    def test_positional_only(self):
        pos, *_, = kn._parse_logs_args(["my-kernel"])
        assert pos == ["my-kernel"]

    def test_follow_flag(self):
        _, follow, *_ = kn._parse_logs_args(["-f"])
        assert follow is True

    def test_follow_long(self):
        _, follow, *_ = kn._parse_logs_args(["--follow"])
        assert follow is True

    def test_browse_flag(self):
        *_, browse, _, _, _ = kn._parse_logs_args(["-b"])
        assert browse is True

    def test_browse_long(self):
        *_, browse, _, _, _ = kn._parse_logs_args(["--browse"])
        assert browse is True

    def test_line_limit(self):
        _, _, limit, *_ = kn._parse_logs_args(["-n", "50"])
        assert limit == 50

    def test_line_limit_at_end(self):
        """-n at end of args without value defaults to 0."""
        _, _, limit, *_ = kn._parse_logs_args(["-n"])
        assert limit == 0

    def test_line_limit_invalid(self):
        _, _, limit, *_ = kn._parse_logs_args(["-n", "notanumber"])
        assert limit == 0

    def test_stream_stdout(self):
        *_, stream, _, _, _, _, _ = kn._parse_logs_args(["--stdout"])
        assert stream == "stdout"

    def test_stream_stderr(self):
        *_, stream, _, _, _, _, _ = kn._parse_logs_args(["--stderr"])
        assert stream == "stderr"

    def test_show_progress(self):
        _, _, _, _, progress, _, _, _, _ = kn._parse_logs_args(["--show-progress"])
        assert progress is True

    def test_help_shorthand(self):
        pos, *_ = kn._parse_logs_args(["help"])
        assert "--help" in pos

    def test_help_flag(self):
        pos, *_ = kn._parse_logs_args(["--help"])
        assert "--help" in pos

    def test_help_short(self):
        pos, *_ = kn._parse_logs_args(["-h"])
        assert "--help" in pos

    def test_multiple_positional(self):
        pos, *_ = kn._parse_logs_args(["kernel1", "kernel2"])
        assert pos == ["kernel1", "kernel2"]

    def test_mixed_flags(self):
        pos, follow, limit, stream, progress, *rest = kn._parse_logs_args(
            ["owner/kernel", "-f", "-n", "20", "--stderr", "--show-progress"]
        )
        assert pos == ["owner/kernel"]
        assert follow is True
        assert limit == 20
        assert stream == "stderr"
        assert progress is True
        assert rest == [False, False, False, False]  # browse, errors_only, summary_view, no_group

    def test_follow_with_browse(self):
        """-f and -b can both be set."""
        _, follow, _, _, _, browse, _, _, _ = kn._parse_logs_args(["-f", "-b"])
        assert follow is True
        assert browse is True


# ── _auto_switch_for_kernel ──────────────────────────────────────


class FakeSwitch:
    """Helper to capture _apply_account_env calls."""

    applied_to = None

    @staticmethod
    def apply(acc):
        FakeSwitch.applied_to = acc


class TestAutoSwitchForKernel:
    def test_no_slash_returns_false(self, config_empty):
        assert kn._auto_switch_for_kernel(config_empty, "my-kernel") is False

    def test_no_slash_returns_false_minimal(self):
        assert kn._auto_switch_for_kernel({"accounts": {}}, "my-kernel") is False

    def test_owner_not_found_returns_false(self, config_empty):
        assert kn._auto_switch_for_kernel(config_empty, "nobody/my-kernel") is False

    def test_already_active_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        cfg = {"accounts": {"1": {"name": "owner", "config_dir": "owner_dir"}}}
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.current_active", lambda c: 1
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.find_account",
            lambda c, ident: Account(number=1, name="owner", config_dir="owner_dir"),
        )
        result = kn._auto_switch_for_kernel(cfg, "owner/my-kernel")
        assert result is False

    def test_different_active_switches(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        cfg = {"accounts": {"1": {"name": "acc1", "config_dir": "acc1_dir"}}}
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.current_active", lambda c: 1
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.find_account",
            lambda c, ident: Account(number=2, name="owner", config_dir="owner_dir"),
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._active_username_from_account",
            lambda a: a.name,
        )
        apply_calls = []

        def fake_apply(acc):
            apply_calls.append(acc)

        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._apply_account_env", fake_apply
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.ok", lambda msg: None
        )
        result = kn._auto_switch_for_kernel(cfg, "owner/my-kernel")
        assert result is True
        assert len(apply_calls) == 1
        assert apply_calls[0].name == "owner"

    def test_owner_via_username_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        cfg = {"accounts": {"1": {"name": "acc1", "config_dir": "acc1_dir"}}}
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.current_active", lambda c: 1
        )

        def find_account_fallback(c, ident):
            return None

        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.find_account", find_account_fallback
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.get_accounts",
            lambda c: [
                Account(number=1, name="acc1", config_dir="acc1_dir"),
                Account(number=2, name="owner", config_dir="owner_dir"),
            ],
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._active_username_from_account",
            lambda a: a.name if a.name == "owner" else None,
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._apply_account_env",
            lambda acc: None,
        )
        monkeypatch.setattr("kaggle_switch.commands.kernel.ok", lambda msg: None)
        result = kn._auto_switch_for_kernel(cfg, "owner/my-kernel")
        assert result is True


# ── cmd_patch ───────────────────────────────────────────────────


class CmdPatchBase:
    @pytest.fixture
    def patch_env(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        cfg_path = tmp_path / ".config" / "kagitch"
        cfg_path.mkdir(parents=True)
        cfg_file = cfg_path / "accounts.json"
        cfg_file.write_text(json.dumps({"accounts": {}}))
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_DIR", cfg_path
        )
        monkeypatch.setattr(
            "kaggle_switch.config.CONFIG_FILE", cfg_file
        )
        return tmp_path


class TestCmdPatch(CmdPatchBase):
    def test_no_args_uses_cwd_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "cwd", classmethod(lambda _: tmp_path))
        with patch("kaggle_switch.commands.kernel._active_username", return_value="testuser"):
            with patch("kaggle_switch.commands.kernel._auto_patch_metadata", return_value=None):
                with patch("kaggle_switch.commands.kernel.console.print"):
                    rc = kn.cmd_patch({"accounts": {}}, [])
        assert rc == 1

    def test_file_not_found(self, tmp_path):
        missing = tmp_path / "nope.json"
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn.cmd_patch({"accounts": {}}, [str(missing)])
        assert rc == 1

    def test_no_active_username(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text("{}")
        with patch("kaggle_switch.commands.kernel._active_username", return_value=None):
            with patch("kaggle_switch.commands.kernel.console.print"):
                rc = kn.cmd_patch({"accounts": {}}, [str(target)])
        assert rc == 1

    def test_patch_fails_returns_1(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text('{"id": "olduser/kernel"}')
        with patch("kaggle_switch.commands.kernel._active_username", return_value="newuser"):
            with patch(
                "kaggle_switch.commands.kernel._auto_patch_metadata",
                return_value=None,
            ):
                with patch("kaggle_switch.commands.kernel.console.print"):
                    rc = kn.cmd_patch({"accounts": {}}, [str(target)])
        assert rc == 1

    def test_patch_success(self, tmp_path):
        target = tmp_path / "kernel-metadata.json"
        target.write_text('{"id": "olduser/kernel"}')
        with patch("kaggle_switch.commands.kernel._active_username", return_value="newuser"):
            with patch(
                "kaggle_switch.commands.kernel._auto_patch_metadata",
                return_value="  \u21b7 [bold]kernel-metadata.json[/]: olduser -> newuser",
            ):
                with patch("kaggle_switch.commands.kernel.console.print"):
                    rc = kn.cmd_patch({"accounts": {}}, [str(target)])
        assert rc == 0

    def test_directory_arg(self, tmp_path):
        sub = tmp_path / "mysub"
        sub.mkdir()
        target = sub / "kernel-metadata.json"
        target.write_text('{"id": "olduser/kernel"}')
        with patch("kaggle_switch.commands.kernel._active_username", return_value="newuser"):
            with patch(
                "kaggle_switch.commands.kernel._auto_patch_metadata",
                return_value="  \u21b7 [bold]kernel-metadata.json[/]: olduser -> newuser",
            ):
                with patch("kaggle_switch.commands.kernel.console.print"):
                    rc = kn.cmd_patch({"accounts": {}}, [str(sub)])
        assert rc == 0


# ── _ask_kernel_init_questions ─────────────────────────────────


class FakeQuestionary:
    """Simulates questionary prompts for _ask_kernel_init_questions."""

    class FakeQuestion:
        def __init__(self, return_value):
            self._return = return_value

        def ask(self):
            return self._return

    @staticmethod
    def text(text, **kwargs):
        return FakeQuestionary.FakeQuestion(kwargs.get("default", "answer"))

    @staticmethod
    def select(text, **kwargs):
        return FakeQuestionary.FakeQuestion(kwargs.get("default", "python"))

    @staticmethod
    def confirm(text, **kwargs):
        return FakeQuestionary.FakeQuestion(kwargs.get("default", True))


class FakeQuestionaryCancel:
    """Return None on the first question (cancel)."""

    call_count = 0

    class FakeQuestion:
        def __init__(self, return_value):
            self._return = return_value

        def ask(self):
            FakeQuestionaryCancel.call_count += 1
            if FakeQuestionaryCancel.call_count == 1:
                return None
            return self._return

    @staticmethod
    def text(text, **kwargs):
        return FakeQuestionaryCancel.FakeQuestion(kwargs.get("default", "answer"))

    @staticmethod
    def select(text, **kwargs):
        return FakeQuestionaryCancel.FakeQuestion(kwargs.get("default", "python"))

    @staticmethod
    def confirm(text, **kwargs):
        return FakeQuestionaryCancel.FakeQuestion(kwargs.get("default", True))


class TestAskKernelInitQuestions:
    def test_returns_answers(self):
        defaults = {
            "title": "My Kernel",
            "slug": "my-kernel",
            "lang": "python",
            "ktype": "script",
            "code_path": "train.py",
        }
        result = kn._ask_kernel_init_questions(
            FakeQuestionary, ">", None, defaults
        )
        assert result is not None
        assert result["title"] == "My Kernel"
        assert result["slug"] == "my-kernel"
        assert result["lang"] == "python"
        assert result["ktype"] == "script"
        assert result["code_path"] == "train.py"
        assert "is_private" in result
        assert "accelerator" in result
        assert "dataset_src" in result
        assert "model_src" in result

    def test_cancel_on_first_question_returns_none(self):
        FakeQuestionaryCancel.call_count = 0
        defaults = {
            "title": "My Kernel",
            "slug": "my-kernel",
            "lang": "python",
            "ktype": "script",
            "code_path": "train.py",
        }
        result = kn._ask_kernel_init_questions(
            FakeQuestionaryCancel, ">", None, defaults
        )
        assert result is None


# ── cmd_kernel_init OSError handler ─────────────────────────────


class TestCmdKernelInitOSError:
    def test_write_failure_returns_1(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "cwd", classmethod(lambda _: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._active_username", lambda c, **kw: None)
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._detect_code_file",
            lambda cwd: tmp_path / "train.py",
        )
        defaults = {
            "title": "My Kernel",
            "slug": "my-kernel",
            "lang": "python",
            "ktype": "script",
            "code_path": "train.py",
            "is_private": True,
            "accelerator": "None",
            "enable_internet": False,
            "dataset_src": "",
            "comp_src": "",
            "kernel_src": "",
            "model_src": "",
        }
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._ask_kernel_init_questions",
            lambda q, qm, qst, d: defaults,
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            from kaggle_switch.commands.kernel import cmd_kernel_init as real_init

            original = Path.write_text

            def fail_write(self, text):
                if self.name == "kernel-metadata.json":
                    raise OSError("denied")
                return original(self, text)

            monkeypatch.setattr(Path, "write_text", fail_write)
            rc = real_init({"accounts": {}}, [])
        assert rc == 1

    def test_cancelled_at_questions_returns_1(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "cwd", classmethod(lambda _: tmp_path))
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._ask_kernel_init_questions",
            lambda q, qm, qst, d: None,
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            from kaggle_switch.commands.kernel import cmd_kernel_init

            rc = cmd_kernel_init({"accounts": {}}, [])
        assert rc == 1

    def test_empty_code_path_returns_1(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "cwd", classmethod(lambda _: tmp_path))
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._active_username", lambda c: None
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._detect_code_file", lambda cwd: None
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._ask_kernel_init_questions",
            lambda q, qm, qst, d: {
                "title": "T",
                "slug": "t",
                "lang": "python",
                "ktype": "script",
                "code_path": "",
                "is_private": True,
                "accelerator": "None",
                "enable_internet": False,
                "dataset_src": "",
                "comp_src": "",
                "kernel_src": "",
                "model_src": "",
            },
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            from kaggle_switch.commands.kernel import cmd_kernel_init

            rc = cmd_kernel_init({"accounts": {}}, [])
        assert rc == 1


# ── cmd_kernel_logs ─────────────────────────────────────────────


class TestCmdKernelLogs:
    def test_help_flag(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.render_logs_help", lambda: None
        )
        rc = kn.cmd_kernel_logs({"accounts": {}}, ["--help"])
        assert rc == 0

    def test_browse_mode(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._browse_kernel_logs", lambda c: 0
        )
        rc = kn.cmd_kernel_logs({"accounts": {}}, [])
        assert rc == 0

    def test_no_positional_triggers_browse(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._browse_kernel_logs", lambda c: 0
        )
        rc = kn.cmd_kernel_logs({"accounts": {}}, ["-b"])
        assert rc == 0

    def test_error_response(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, k: False
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs",
            lambda k: type("R", (), {"error": "not found", "entries": []})(),
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn.cmd_kernel_logs({"accounts": {}}, ["owner/kernel"])
        assert rc == 1

    def test_follow_mode(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, k: False
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )

        class FakeResult:
            error = ""
            entries = [MagicMock(data="line1", timestamp=0)]

        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs", lambda k: FakeResult()
        )
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs_follow",
            lambda k, on_status: iter([FakeResult().entries]),
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn.cmd_kernel_logs({"accounts": {}}, ["owner/kernel", "-f", "--stdout", "-n", "10"])
        assert rc == 0

    def test_follow_keyboard_interrupt(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, k: False
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )

        class FakeResult:
            error = ""
            entries = [MagicMock(data="line1", timestamp=0)]

        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs", lambda k: FakeResult()
        )

        def interrupting_gen(kernel, on_status):
            raise KeyboardInterrupt
            yield None

        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs_follow", interrupting_gen
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn.cmd_kernel_logs({"accounts": {}}, ["owner/kernel", "-f"])
        assert rc == 0

    def test_simple_logs_with_stream_and_limit(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, k: False
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )

        class FakeResult:
            error = ""
            entries = [
                MagicMock(stream="stderr", data="err1"),
                MagicMock(stream="stdout", data="out1"),
            ]

        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs", lambda k: FakeResult()
        )
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.render_result", lambda r, **kw: None
        )
        rc = kn.cmd_kernel_logs({"accounts": {}}, ["kernel", "--stderr", "-n", "5"])
        assert rc == 0

    def test_follow_with_stream_filter(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, k: False
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )

        class FakeResult:
            error = ""
            entries = [MagicMock(data="line1", timestamp=0)]

        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs", lambda k: FakeResult()
        )

        batch = [
            MagicMock(stream="stdout", data="out1", timestamp=0),
            MagicMock(stream="stderr", data="err1", timestamp=0),
        ]

        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs_follow",
            lambda k, on_status: iter([batch]),
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn.cmd_kernel_logs({"accounts": {}}, ["kernel", "-f", "--stdout"])
        assert rc == 0


# ── _browse_kernel_logs ─────────────────────────────────────────


class MockLogEntry:
    def __init__(self, data, stream="stdout"):
        self.data = data
        self.stream = stream


class MockKernelInfo:
    def __init__(self, ref, title="", status="", last_run_time=""):
        self.ref = ref
        self.title = title
        self.status = status
        self.last_run_time = last_run_time


class TestBrowseKernelLogs:
    def test_no_account_returns_1(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: None,
        )
        rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 1

    def test_no_kernels_returns_1(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: acc,
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._apply_account_env", lambda a: None
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.list_kernels", lambda owner: []
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._active_username_from_account",
            lambda a: a.name,
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 1

    def test_error_on_fetch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: acc,
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._apply_account_env", lambda a: None
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._active_username_from_account",
            lambda a: a.name,
        )
        kernels = [MockKernelInfo(ref="testacc/kernel1", title="K1", status="COMPLETE", last_run_time="2024-01-01")]
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.list_kernels", lambda owner: kernels
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._terminal_select",
            lambda options, **kw: 0,
        )
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs",
            lambda k: type("R", (), {"error": "failed", "entries": []})(),
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 1

    def test_happy_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: acc,
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._apply_account_env", lambda a: None
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._active_username_from_account",
            lambda a: a.name,
        )
        kernels = [MockKernelInfo(ref="testacc/kernel1", title="K1", status="COMPLETE", last_run_time="2024-01-01")]
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.list_kernels", lambda owner: kernels
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._terminal_select",
            lambda options, **kw: 0,
        )

        class FakeLogResult:
            error = ""
            entries = [MockLogEntry("log line 1")]

        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.fetch_logs", lambda k: FakeLogResult()
        )
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.render_result", lambda r, **kw: None
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 0

    def test_happy_path_uses_filterable_slug_options(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: acc,
        )
        monkeypatch.setattr("kaggle_switch.commands.kernel._apply_account_env", lambda a: None)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", lambda msg: nullcontext())
        monkeypatch.setattr("kaggle_switch.commands.kernel._active_username_from_account", lambda a: a.name)
        kernels = [MockKernelInfo(ref="testacc/kernel1", title="K1", status="COMPLETE", last_run_time="2024-01-01")]
        monkeypatch.setattr("kaggle_switch.logs_viewer.list_kernels", lambda owner: kernels)
        captured = {}

        def fake_select(options, **kw):
            captured["options"] = options
            captured["kwargs"] = kw
            return 0

        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_select", fake_select)
        monkeypatch.setattr("kaggle_switch.logs_viewer.fetch_logs", lambda k: type("R", (), {"error": "", "entries": []})())
        monkeypatch.setattr("kaggle_switch.logs_viewer.render_result", lambda r, **kw: None)
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 0
        assert captured["kwargs"]["filterable"] is True
        assert "kernel1" in captured["options"][0]
        assert "testacc/" not in captured["options"][0]

    def test_happy_path_selector_title_counts(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: acc,
        )
        monkeypatch.setattr("kaggle_switch.commands.kernel._apply_account_env", lambda a: None)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", lambda msg: nullcontext())
        monkeypatch.setattr("kaggle_switch.commands.kernel._active_username_from_account", lambda a: a.name)
        kernels = [MockKernelInfo(ref="testacc/kernel1", title="K1", status="COMPLETE", last_run_time="2024-01-01")]
        monkeypatch.setattr("kaggle_switch.logs_viewer.list_kernels", lambda owner: kernels)
        captured = {}

        def fake_select(options, **kw):
            captured["kwargs"] = kw
            return 0

        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_select", fake_select)
        monkeypatch.setattr("kaggle_switch.logs_viewer.fetch_logs", lambda k: type("R", (), {"error": "", "entries": []})())
        monkeypatch.setattr("kaggle_switch.logs_viewer.render_result", lambda r, **kw: None)
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 0
        assert "testacc" in captured["kwargs"]["title"]
        assert "1 kernels" in captured["kwargs"]["title"]
        assert "lọc" in captured["kwargs"]["footer"]

    def test_terminal_select_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: acc,
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._apply_account_env", lambda a: None
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._tty_status",
            lambda msg: MagicMock(
                __enter__=lambda _: None, __exit__=lambda *a: None
            ),
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel._active_username_from_account",
            lambda a: a.name,
        )
        kernels = [MockKernelInfo(ref="testacc/kernel1")]
        monkeypatch.setattr(
            "kaggle_switch.logs_viewer.list_kernels", lambda owner: kernels
        )
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._terminal_select",
            lambda options, **kw: None,
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 1


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def config_empty():
    return {"accounts": {}}


# ── kagitch kernel output ───────────────────────────────────────


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(out: str) -> str:
    return _ANSI_RE.sub("", out)


class TestParseKernelOutputArgs:
    def test_defaults(self):
        args = kn._parse_kernel_output_args([])
        assert args is not None
        assert args["ref"] is None
        assert args["all"] is False
        assert args["force"] is False
        assert args["path"] is None
        assert args["help"] is False

    def test_parses_flags(self):
        args = kn._parse_kernel_output_args(["-a", "-f", "-p", "out", "owner/slug"])
        assert args["ref"] == "owner/slug"
        assert args["all"] is True
        assert args["force"] is True
        assert args["path"] == "out"

    def test_help_flag(self):
        args = kn._parse_kernel_output_args(["--help"])
        assert args["help"] is True

    def test_unknown_flag_returns_none(self):
        assert kn._parse_kernel_output_args(["-z"]) is None

    def test_missing_path_value_returns_none(self):
        assert kn._parse_kernel_output_args(["-p"]) is None

    def test_too_many_positionals_returns_none(self):
        assert kn._parse_kernel_output_args(["a/b", "c/d"]) is None


class _TtyStatus:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


def _tty_status_factory(msg=""):
    return _TtyStatus()


class TestCmdKernelOutput:
    @pytest.fixture(autouse=True)
    def _tty_and_no_sizes(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.fetch_sizes", lambda files, **kw: None)

    def test_help(self, capsys):
        rc = kn.cmd_kernel_output({"accounts": {}}, ["--help"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "kagitch kernel output" in out

    def test_bad_args_usage(self, capsys):
        rc = kn.cmd_kernel_output({"accounts": {}}, ["-z"])
        assert rc == 1
        assert "Usage: kagitch kernel output" in capsys.readouterr().out

    def test_ref_without_owner_returns_1(self, capsys, monkeypatch):
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        rc = kn.cmd_kernel_output({"accounts": {}}, ["noslash"])
        assert rc == 1

    def test_auto_switch_fail_returns_1(self, capsys, monkeypatch):
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: False)
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])
        assert rc == 1

    def test_all_mode_subprocess(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        called = {}

        def fake_run(cmd, **kwargs):
            called["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("kaggle_switch.commands.kernel.subprocess.run", fake_run)
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug", "-a", "-p", "out", "-f"])
        assert rc == 0
        assert called["cmd"] == [
            "kaggle", "kernels", "output", "download", "owner/slug",
            "-p", "out", "-o",
        ]

    def test_all_mode_nonzero_rc(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.subprocess.run",
            lambda cmd, **kw: SimpleNamespace(returncode=2),
        )
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug", "-a"])
        assert rc == 2

    def test_all_mode_missing_cli(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.subprocess.run",
            lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError()),
        )
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug", "-a"])
        assert rc == 1
        assert "kaggle CLI not found" in capsys.readouterr().out

    def test_select_mode_success(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        from kaggle_switch.kernel_outputs import OutputFile

        files = [
            OutputFile(path="a.csv", url="http://u/a"),
            OutputFile(path="data/b.csv", url="http://u/b"),
            OutputFile(path="slug.log", url=None, log_text="log"),
        ]
        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: files)

        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"a.csv", "data/b.csv", "slug.log"})
        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files",
                            lambda f, t, **kw: ([t / f2.path for f2 in f], 0))

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "Downloaded 3 file(s)" in _plain(out)
        assert (tmp_path / "slug-output").is_dir()

    def test_select_subset_of_tree(self, capsys, monkeypatch, tmp_path):
        """Only the checked tree paths are downloaded."""
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        from kaggle_switch.kernel_outputs import OutputFile

        files = [
            OutputFile(path="a.csv", url="http://u/a"),
            OutputFile(path="data/b.csv", url="http://u/b"),
            OutputFile(path="data/sub/c.csv", url="http://u/c"),
        ]
        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: files)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"data/b.csv"})
        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files",
                            lambda f, t, **kw: ([t / f2.path for f2 in f], 0))

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "Downloaded 1 file(s)" in _plain(out)

    def test_select_mode_tree_cancel(self, capsys, monkeypatch, tmp_path):
        """A cancelled tree picker aborts the selection."""
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        from kaggle_switch.kernel_outputs import OutputFile

        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: [OutputFile(path="data/b.csv", url="http://u/b")])
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: None)

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 1

    def test_select_mode_skip_warning(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        from kaggle_switch.kernel_outputs import OutputFile

        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a")])

        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"a.csv"})
        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files",
                            lambda f, t, **kw: ([t / "a.csv"], 1))

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 0
        assert "Skipped 1" in _plain(capsys.readouterr().out)

    def test_empty_files_returns_1(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: [])
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])
        assert rc == 1
        assert "No output files" in capsys.readouterr().out

    def test_listing_error_returns_1(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        from kaggle_switch.kernel_outputs import KernelOutputError

        def boom(o, s, **kw):
            raise KernelOutputError("nope")

        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files", boom)
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])
        assert rc == 1
        assert "nope" in capsys.readouterr().out

    def test_selection_cancel_returns_1(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        from kaggle_switch.kernel_outputs import OutputFile

        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a")])
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: None)
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])
        assert rc == 1
        assert "Cancelled" in capsys.readouterr().out

    def test_download_error_returns_1(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        from kaggle_switch.kernel_outputs import KernelOutputError, OutputFile

        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a")])
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"a.csv"})
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs.download_files",
            lambda f, t, **kw: (_ for _ in ()).throw(KernelOutputError("expired")),
        )
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])
        assert rc == 1
        assert "expired" in capsys.readouterr().out


def _patch_browse(monkeypatch, tmp_path, kernels, select_result):
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
    monkeypatch.setattr("kaggle_switch.commands.kernel._apply_account_env", lambda a: None)
    monkeypatch.setattr("kaggle_switch.commands.kernel._active_username_from_account",
                        lambda a: a.name)
    monkeypatch.setattr("kaggle_switch.logs_viewer.list_kernels", lambda owner: kernels)
    monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_select",
                        lambda options, **kw: select_result)


class TestBrowseKernelOutput:
    @pytest.fixture(autouse=True)
    def _tty_and_no_sizes(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.fetch_sizes", lambda files, **kw: None)

    def test_account_cancel_returns_1(self, monkeypatch):
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._select_account_interactive",
                            lambda c, **kw: None)
        assert kn.cmd_kernel_output({"accounts": {}}, []) == 1

    def test_no_kernels_returns_1(self, monkeypatch, tmp_path):
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._select_account_interactive",
                            lambda c, **kw: acc)
        _patch_browse(monkeypatch, tmp_path, [], 0)
        assert kn.cmd_kernel_output({"accounts": {}}, []) == 1

    def test_kernel_cancel_returns_1(self, monkeypatch, tmp_path):
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._select_account_interactive",
                            lambda c, **kw: acc)
        _patch_browse(monkeypatch, tmp_path, [MockKernelInfo(ref="t/k1")], None)
        assert kn.cmd_kernel_output({"accounts": {}}, []) == 1

    def test_browse_full_flow(self, capsys, monkeypatch, tmp_path):
        from kaggle_switch.kernel_outputs import OutputFile

        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._select_account_interactive",
                            lambda c, **kw: acc)
        _patch_browse(monkeypatch, tmp_path, [MockKernelInfo(ref="testacc/k1")], 0)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a")])
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"a.csv"})
        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files",
                            lambda f, t, **kw: ([t / "a.csv"], 0))

        rc = kn.cmd_kernel_output({"accounts": {}}, [])

        assert rc == 0
        assert "Downloaded 1 file(s)" in _plain(capsys.readouterr().out)


class TestKernelOutputCoverage:
    @pytest.fixture(autouse=True)
    def _tty_and_no_sizes(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.fetch_sizes", lambda files, **kw: None)

    def test_all_mode_timeout(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.subprocess.run",
            lambda cmd, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="kaggle", timeout=600)),
        )
        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug", "-a"])
        assert rc == 1
        assert "timed out" in capsys.readouterr().out

    def test_browse_with_status_color(self, capsys, monkeypatch, tmp_path):
        """Browse flow with a RUNNING kernel status."""
        from kaggle_switch.kernel_outputs import OutputFile

        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: acc,
        )
        _patch_browse(
            monkeypatch, tmp_path, [MockKernelInfo(ref="testacc/k1", status="RUNNING")], 0
        )
        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a")])
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"a.csv"})
        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files",
                            lambda f, t, **kw: ([t / "a.csv"], 0))

        rc = kn.cmd_kernel_output({"accounts": {}}, [])

        assert rc == 0

    def test_browse_with_unknown_status_color(self, capsys, monkeypatch, tmp_path):
        """Browse flow with an unknown kernel status."""
        from kaggle_switch.kernel_outputs import OutputFile

        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c, **kw: acc,
        )
        _patch_browse(
            monkeypatch, tmp_path, [MockKernelInfo(ref="testacc/k1", status="QUEUED")], 0
        )
        monkeypatch.setattr("kaggle_switch.kernel_outputs.list_output_files",
                            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a")])
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"a.csv"})
        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files",
                            lambda f, t, **kw: ([t / "a.csv"], 0))

        rc = kn.cmd_kernel_output({"accounts": {}}, [])

        assert rc == 0


class TestKernelOutputUI:
    @pytest.fixture(autouse=True)
    def _tty_and_no_sizes(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.fetch_sizes", lambda files, **kw: None)

    def test_fmt_bytes(self):
        assert kn._fmt_bytes(None) == "?"
        assert kn._fmt_bytes(0) == "0 B"
        assert kn._fmt_bytes(1023) == "1023 B"
        assert kn._fmt_bytes(1024) == "1.0 KB"
        assert kn._fmt_bytes(1536) == "1.5 KB"
        assert kn._fmt_bytes(5 * 1024 * 1024) == "5.0 MB"

    def test_tree_picker_receives_structure(self, capsys, monkeypatch, tmp_path):
        """The interactive tree picker gets nested items with sizes."""
        from kaggle_switch.kernel_outputs import OutputFile

        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs.list_output_files",
            lambda o, s, **kw: [OutputFile(path="data/train.csv", url="http://u/a", size=2048)],
        )
        captured = {}

        def fake_tree(items, *, title, footer):
            captured["items"] = items
            captured["title"] = title
            return {"data/train.csv"}

        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", fake_tree)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files",
                            lambda f, t, **kw: ([t / "data/train.csv"], 0))

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 0
        assert "owner/slug" in captured["title"]
        assert len(captured["items"]) == 1
        d = captured["items"][0]
        assert d.label == "data"
        assert d.path == "data"
        assert d.children[0].label == "train.csv"
        assert d.children[0].size == "2.0 KB"
        assert "Output download" in _plain(capsys.readouterr().out)

    def test_non_tty_stdin_degradation(self, capsys, monkeypatch, tmp_path):
        """Interactive selection refuses to run without a terminal."""
        from kaggle_switch.kernel_outputs import OutputFile

        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs.list_output_files",
            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a")],
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 1
        assert "needs a terminal" in _plain(capsys.readouterr().out)

    def test_summary_card_with_size(self, capsys, monkeypatch, tmp_path):
        """Summary card shows total bytes reported through on_progress."""
        from kaggle_switch.kernel_outputs import OutputFile

        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs.list_output_files",
            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a", size=512)],
        )
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"a.csv"})

        def fake_download(files, target, *, force=False, on_progress=None, **kw):
            dest = target / "a.csv"
            if on_progress:
                on_progress(dest, 512, 512)
            return ([dest], 0)

        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files", fake_download)

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 0
        out = _plain(capsys.readouterr().out)
        assert "Size:" in out
        assert "512 B" in out


class TestKernelOutputUIExtra:
    @pytest.fixture(autouse=True)
    def _tty_and_no_sizes(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.fetch_sizes", lambda files, **kw: None)

    def test_empty_files_returns_empty(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        assert kn._select_output_files([], "owner/slug") == []

    def test_tree_cancel_in_browse(self, capsys, monkeypatch, tmp_path):
        """A cancelled tree picker aborts the whole flow."""
        from kaggle_switch.kernel_outputs import OutputFile

        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs.list_output_files",
            lambda o, s, **kw: [OutputFile(path="data/b.csv", url="http://u/b")],
        )
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: None)

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 1
        assert "Cancelled" in _plain(capsys.readouterr().out)

    def test_tty_progress_path(self, capsys, monkeypatch, tmp_path):
        """TTY stdout uses the live Progress bar and reports bytes."""
        from kaggle_switch.kernel_outputs import OutputFile

        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs.list_output_files",
            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a", size=512)],
        )
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._terminal_tree_select", lambda *a, **kw: {"a.csv"})

        def fake_download(files, target, *, force=False, on_progress=None, **kw):
            dest = target / "a.csv"
            if on_progress:
                on_progress(dest, 512, 512)
            return ([dest], 0)

        monkeypatch.setattr("kaggle_switch.kernel_outputs.download_files", fake_download)

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 0
        out = _plain(capsys.readouterr().out)
        assert "Downloaded 1 file(s)" in out
        assert "512 B" in out

    def test_fetch_sizes_error_returns_1(self, capsys, monkeypatch, tmp_path):
        """A failed size fetch aborts with a friendly message."""
        from kaggle_switch.kernel_outputs import KernelOutputError, OutputFile

        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr("kaggle_switch.commands.kernel._auto_switch_for_kernel", lambda c, r: True)
        monkeypatch.setattr("kaggle_switch.commands.kernel.display._tty_status", _tty_status_factory)
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs.list_output_files",
            lambda o, s, **kw: [OutputFile(path="a.csv", url="http://u/a")],
        )

        def boom(files, **kw):
            raise KernelOutputError("sizes failed")

        monkeypatch.setattr("kaggle_switch.kernel_outputs.fetch_sizes", boom)

        rc = kn.cmd_kernel_output({"accounts": {}}, ["owner/slug"])

        assert rc == 1
        assert "sizes failed" in _plain(capsys.readouterr().out)
