"""Tests for kernel command module."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

import kaggle_switch.logs_viewer as lv
from kaggle_switch.commands import kernel as kn
from kaggle_switch.config import Account, load_config, save_config
from kaggle_switch.commands.switch import _apply_account_env


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


# ── _parse_logs_args ────────────────────────────────────────────


class TestParseLogsArgs:
    def test_empty(self):
        pos, follow, limit, stream, progress, browse = kn._parse_logs_args([])
        assert pos == []
        assert follow is False
        assert limit == 0
        assert stream is None
        assert progress is False
        assert browse is False

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
        *_, browse = kn._parse_logs_args(["-b"])
        assert browse is True

    def test_browse_long(self):
        *_, browse = kn._parse_logs_args(["--browse"])
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
        *_, stream, _, _ = kn._parse_logs_args(["--stdout"])
        assert stream == "stdout"

    def test_stream_stderr(self):
        *_, stream, _, _ = kn._parse_logs_args(["--stderr"])
        assert stream == "stderr"

    def test_show_progress(self):
        _, _, _, _, progress, _ = kn._parse_logs_args(["--show-progress"])
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
        pos, follow, limit, stream, progress, browse = kn._parse_logs_args(
            ["owner/kernel", "-f", "-n", "20", "--stderr", "--show-progress"]
        )
        assert pos == ["owner/kernel"]
        assert follow is True
        assert limit == 20
        assert stream == "stderr"
        assert progress is True

    def test_follow_with_browse(self):
        """-f and -b can both be set."""
        _, follow, _, _, _, browse = kn._parse_logs_args(["-f", "-b"])
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
        monkeypatch.setattr("kaggle_switch.commands.kernel._active_username", lambda c: None)
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
            lambda c: None,
        )
        rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 1

    def test_no_kernels_returns_1(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c: acc,
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
            lambda c: acc,
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
            lambda options: 0,
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
            lambda c: acc,
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
            lambda options: 0,
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

    def test_terminal_select_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        acc = Account(number=1, name="testacc", config_dir="testacc")
        monkeypatch.setattr(
            "kaggle_switch.commands.kernel.display._select_account_interactive",
            lambda c: acc,
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
            lambda options: None,
        )
        with patch("kaggle_switch.commands.kernel.console.print"):
            rc = kn._browse_kernel_logs({"accounts": {}})
        assert rc == 1


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def config_empty():
    return {"accounts": {}}
