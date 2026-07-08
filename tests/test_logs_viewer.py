"""Tests for logs_viewer module."""
import io
import json
import subprocess
from unittest.mock import Mock, patch

from rich.console import Console

from kaggle_switch import logs_viewer as lv
from kaggle_switch.logs_viewer import (
    LogEntry,
    LogFetchResult,
    _classify_line,
    _format_timestamp,
    _infer_fix_hint,
    _is_progress_bar,
    _parse_plain_logs,
    _parse_stream_events,
    _poll_follow,
    _stream_follow,
    fetch_logs_follow,
    get_kernel_status,
    list_kernels,
    render_logs,
    render_logs_help,
    render_result,
)


# ── Sample log data ─────────────────────────────────────────────

_LOG_TEXT = """Training epoch 1/20  batch 256
FloatingPointError: NaN in loss
line1
line2
line3
Cloning into repo..."""


# ── Sample SSE events ────────────────────────────────────────

_STREAM_EVENTS = [
    {"data": "Training epoch 1/20  batch 256\n", "stream_name": "stdout", "time": "1719000000"},
    {"data": "FloatingPointError: NaN in loss\n", "stream_name": "stderr", "time": "1719000001"},
    {"data": "line1\nline2\nline3\n", "stream_name": "stdout", "time": "1719000002"},
    {"data": "Cloning into repo...\n", "stream_name": "stdout", "time": "1719000003"},
]


class TestParseStreamEvents:
    def test_empty(self):
        result = _parse_stream_events([])
        assert result.entries == []
        assert result.error == ""

    def test_multiple_events(self):
        result = _parse_stream_events(_STREAM_EVENTS)
        assert len(result.entries) == 6
        assert result.entries[0].data == "Training epoch 1/20  batch 256"
        assert result.entries[0].stream == "stdout"
        assert result.entries[0].timestamp == 1719000000.0
        assert result.entries[1].data == "FloatingPointError: NaN in loss"
        assert result.entries[1].stream == "stderr"
        assert result.entries[1].timestamp == 1719000001.0

    def test_streams_preserved(self):
        result = _parse_stream_events(_STREAM_EVENTS)
        assert result.entries[0].stream == "stdout"
        assert result.entries[1].stream == "stderr"
        assert result.entries[2].stream == "stdout"

    def test_multiline_event_split(self):
        result = _parse_stream_events(_STREAM_EVENTS)
        assert result.entries[2].data == "line1"
        assert result.entries[3].data == "line2"
        assert result.entries[4].data == "line3"

    def test_missing_fields_default(self):
        events = [{"data": "orphan\n"}]
        result = _parse_stream_events(events)
        assert len(result.entries) == 1
        assert result.entries[0].stream == "stdout"
        assert result.entries[0].timestamp == 0.0

    def test_null_data(self):
        events = [{"data": None, "stream_name": "stdout", "time": "100"}]
        result = _parse_stream_events(events)
        assert result.entries == []

    def test_status_always_empty(self):
        result = _parse_stream_events([])
        assert result.status == ""


class TestParsePlainLogs:
    def test_empty(self):
        result = _parse_plain_logs("")
        assert result.entries == []
        assert result.error == ""

    def test_whitespace_only(self):
        result = _parse_plain_logs("  \n  \n  ")
        assert result.entries == []
        assert result.error == ""

    def test_multiple_lines(self):
        result = _parse_plain_logs(_LOG_TEXT)
        assert len(result.entries) == 6
        assert result.entries[0].data == "Training epoch 1/20  batch 256"
        assert result.entries[1].data == "FloatingPointError: NaN in loss"
        assert result.entries[2].data == "line1"
        assert result.entries[3].data == "line2"
        assert result.entries[4].data == "line3"
        assert result.entries[5].data == "Cloning into repo..."

    def test_all_entries_are_stdout(self):
        result = _parse_plain_logs(_LOG_TEXT)
        assert all(e.stream == "stdout" for e in result.entries)

    def test_all_timestamps_zero(self):
        result = _parse_plain_logs(_LOG_TEXT)
        assert all(e.timestamp == 0.0 for e in result.entries)

    def test_single_line(self):
        result = _parse_plain_logs("Just one line")
        assert len(result.entries) == 1
        assert result.entries[0].data == "Just one line"

    def test_trailing_newline(self):
        result = _parse_plain_logs("line1\nline2\n")
        assert len(result.entries) == 2

    def test_status_always_empty(self):
        result = _parse_plain_logs(_LOG_TEXT)
        assert result.status == ""


class TestFormatTimestamp:
    def test_zero(self):
        assert _format_timestamp(0) == " " * 8

    def test_relative_time(self):
        assert _format_timestamp(10.5, 0.0) == "+ 10.5s"
        assert _format_timestamp(99.9, 0.0) == "+ 99.9s"

    def test_seconds_only_past_100(self):
        ts = _format_timestamp(150.0, 0.0)
        assert "s" in ts
        assert "+" in ts


class TestClassifyLine:
    def test_error_line(self):
        assert _classify_line("Traceback (most recent call last):", "stderr") == ("\u2718", "bold red")
        assert _classify_line("RuntimeError: CUDA out of memory", "stderr") == ("\u2718", "bold red")
        assert _classify_line("Exception: something broke", "stderr") == ("\u2718", "bold red")

    def test_warning_line(self):
        assert _classify_line("UserWarning: Some deprecation", "stderr") == ("\u26a0", "yellow")
        assert _classify_line("incompatible", "stderr") == ("\u26a0", "yellow")

    def test_metric_line(self):
        icon, style = _classify_line("Epoch 1: loss=0.3509", "stdout")
        assert icon == "\u25b6" and "cyan" in style

        icon, style = _classify_line("  IWildCamVal Top-1 accuracy: 0.4272", "stderr")
        assert icon == "\u25b6" and "cyan" in style

    def test_noise_line(self):
        assert _classify_line("wandb: Syncing run ...", "stderr") == ("\u00b7", "bright_black")

    def test_source_filler(self):
        assert _classify_line("  return super().apply(*args, **kwargs)", "stderr") == ("\u00b7", "bright_black")
        assert _classify_line("    self.check_worker_number_rationality()", "stderr")[0] == "\u00b7"

    def test_normal_stdout(self):
        assert _classify_line("Cloning into repo...", "stdout") == ("\u25b6", "default")

    def test_normal_stderr_info(self):
        assert _classify_line("Using DataParallel on 2 CUDA devices", "stderr") == ("\u00b7", "dim")


class TestInferFixHint:
    def test_cuda_oom(self):
        entries = [LogEntry("stdout", 0, "CUDA out of memory")]
        assert _infer_fix_hint(entries) is not None

    def test_fpe_hint(self):
        entries = [LogEntry("stderr", 0, "FloatingPointError")]
        assert _infer_fix_hint(entries) is not None

    def test_no_hint(self):
        entries = [LogEntry("stdout", 0, "Everything looks good")]
        assert _infer_fix_hint(entries) is None

    def test_empty(self):
        assert _infer_fix_hint([]) is None


# ── API-based fetch (primary path) ─────────────────────────────

class TestFetchLogsWithApi:
    """Tests for fetch_logs using the Kaggle Python API (primary path)."""

    def test_success(self):
        """Stream events from mock API return structured LogEntries."""
        mock_api = Mock()
        mock_api.kernels_logs_stream.return_value = iter([
            {"data": "line1\n", "stream_name": "stdout", "time": "1000"},
            {"data": "line2\n", "stream_name": "stderr", "time": "1001"},
        ])
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=mock_api):
            from kaggle_switch.logs_viewer import fetch_logs
            result = fetch_logs("user/kernel")
        assert result.error == ""
        assert len(result.entries) == 2
        assert result.entries[0].data == "line1"
        assert result.entries[0].stream == "stdout"
        assert result.entries[0].timestamp == 1000.0
        assert result.entries[1].data == "line2"
        assert result.entries[1].stream == "stderr"
        assert result.entries[1].timestamp == 1001.0

    def test_api_authentication_failure(self):
        """When _try_kaggle_api returns None, fallback to subprocess."""
        mock_run = Mock()
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_LOG_TEXT, stderr="",
        )
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=None):
            with patch("kaggle_switch.logs_viewer.subprocess.run", return_value=mock_run.return_value):
                from kaggle_switch.logs_viewer import fetch_logs
                result = fetch_logs("user/kernel")
        assert len(result.entries) == 6
        assert result.error == ""

    def test_api_stream_error(self):
        """API stream error returns error result, does not crash."""
        mock_api = Mock()
        mock_api.kernels_logs_stream.side_effect = RuntimeError("connection failed")
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=mock_api):
            from kaggle_switch.logs_viewer import fetch_logs
            result = fetch_logs("user/kernel")
        assert result.error != ""


# ── Subprocess fallback ─────────────────────────────────────────

class TestFetchLogsSubprocess:
    """Tests for fetch_logs subprocess fallback path."""

    def test_kaggle_not_found(self):
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=None):
            with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError()
                from kaggle_switch.logs_viewer import fetch_logs
                result = fetch_logs("user/kernel")
                assert result.error != ""
                assert "kaggle CLI not found" in result.error

    def test_timeout(self):
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=None):
            with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired(cmd="", timeout=60)
                from kaggle_switch.logs_viewer import fetch_logs
                result = fetch_logs("user/kernel")
                assert result.error != ""
                assert "timed out" in result.error

    def test_nonzero_returncode(self):
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=None):
            with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr="Error: not found",
                )
                from kaggle_switch.logs_viewer import fetch_logs
                result = fetch_logs("user/kernel")
                assert "not found" in result.error

    def test_success(self):
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=None):
            with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=_LOG_TEXT, stderr="",
                )
                from kaggle_switch.logs_viewer import fetch_logs
                result = fetch_logs("user/kernel")
                assert len(result.entries) == 6
                assert result.error == ""

    def test_does_not_pass_json_flag(self):
        """Verify --json is NOT passed to the kaggle CLI."""
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=None):
            with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr="",
                )
                from kaggle_switch.logs_viewer import fetch_logs
                fetch_logs("user/kernel")
                args = mock_run.call_args[0][0]
                assert "--json" not in args


class TestRenderResult:
    def test_error_shows_error(self, capsys):
        result = LogFetchResult(error="Kernel not found")
        render_result(result)
        captured = capsys.readouterr()
        assert "Kernel not found" in captured.out

    def test_empty_entries(self, capsys):
        result = LogFetchResult()
        render_result(result)
        captured = capsys.readouterr()
        assert "output yet" in captured.out

    def test_normal_entries(self, capsys):
        from kaggle_switch.logs_viewer import LogEntry
        result = LogFetchResult(entries=[
            LogEntry("stdout", 1719000000.0, "Training started"),
        ])
        render_result(result)
        captured = capsys.readouterr()
        assert "Training started" in captured.out


class TestKernelStatus:
    def test_success_parses_status(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='owner/slug has status "KernelWorkerStatus.COMPLETE"',
                stderr="",
            )
            assert get_kernel_status("owner/slug") == "COMPLETE"

    def test_nonzero_returncode(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="bad")
            assert get_kernel_status("owner/slug") == ""

    def test_unparseable_stdout(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="no status here", stderr="")
            assert get_kernel_status("owner/slug") == ""

    def test_file_not_found(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run", side_effect=FileNotFoundError):
            assert get_kernel_status("owner/slug") == ""

    def test_timeout(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=30)):
            assert get_kernel_status("owner/slug") == ""


class TestListKernels:
    def test_success_sorted_newest_first(self):
        payload = [
            {"ref": "owner/older", "title": "Older", "lastRunTime": "2024-01-01T00:00:00Z"},
            {"ref": "owner/newer", "title": "Newer", "lastRunTime": "2024-01-02T00:00:00Z"},
        ]
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run, \
             patch("kaggle_switch.logs_viewer.get_kernel_status", side_effect=["RUNNING", "COMPLETE"]):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
            result = list_kernels("owner")

        assert [k.ref for k in result] == ["owner/newer", "owner/older"]
        assert result[0].status == "COMPLETE"
        assert result[1].status == "RUNNING"

    def test_empty_stdout(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="  ", stderr="")
            assert list_kernels("owner") == []

    def test_non_list_json(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps({"ref": "x"}), stderr="")
            assert list_kernels("owner") == []

    def test_invalid_json(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="{", stderr="")
            assert list_kernels("owner") == []

    def test_nonzero_returncode(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="bad")
            assert list_kernels("owner") == []

    def test_timeout(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=30)):
            assert list_kernels("owner") == []

    def test_file_not_found(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run", side_effect=FileNotFoundError):
            assert list_kernels("owner") == []

    def test_skips_private_kernel_empty_ref(self):
        payload = [
            {"ref": "", "title": "Private", "lastRunTime": "2024-01-01T00:00:00Z"},
            {"ref": "owner/public", "title": "Public", "lastRunTime": "2024-01-02T00:00:00Z"},
        ]
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run, \
             patch("kaggle_switch.logs_viewer.get_kernel_status", return_value="COMPLETE"):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
            result = list_kernels("owner")
        assert len(result) == 1
        assert result[0].ref == "owner/public"

    def test_status_fetch_exception_fallback_empty(self):
        payload = [{"ref": "owner/public", "title": "Public", "lastRunTime": "2024-01-02T00:00:00Z"}]
        with patch("kaggle_switch.logs_viewer.subprocess.run") as mock_run, \
             patch("kaggle_switch.logs_viewer.get_kernel_status", side_effect=RuntimeError("boom")):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
            result = list_kernels("owner")
        assert len(result) == 1
        assert result[0].status == ""


class TestFollowMode:
    def test_fetch_logs_follow_uses_stream_api(self):
        mock_api = Mock()
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=mock_api), \
             patch("kaggle_switch.logs_viewer._stream_follow", return_value=iter([[LogEntry("stdout", 1.0, "a")]])) as mock_stream:
            it = fetch_logs_follow("owner/kernel")
            batches = list(it)
        assert len(batches) == 1
        mock_stream.assert_called_once_with("owner/kernel", mock_api)

    def test_fetch_logs_follow_falls_back_to_poll(self):
        with patch("kaggle_switch.logs_viewer._try_kaggle_api", return_value=None), \
             patch("kaggle_switch.logs_viewer._poll_follow", return_value=iter([[LogEntry("stdout", 1.0, "b")]])) as mock_poll:
            it = fetch_logs_follow("owner/kernel")
            batches = list(it)
        assert len(batches) == 1
        mock_poll.assert_called_once_with("owner/kernel")

    def test_stream_follow_yields_batches_of_ten_and_remainder(self):
        mock_api = Mock()
        events = [
            {"data": f"line{i}\n", "stream_name": "stdout", "time": str(1000 + i)}
            for i in range(11)
        ]
        mock_api.kernels_logs_stream.return_value = iter(events)
        batches = list(_stream_follow("owner/kernel", mock_api))
        assert len(batches) == 2
        assert len(batches[0]) == 10
        assert len(batches[1]) == 1

    def test_poll_follow_yields_new_then_stops_on_stale(self):
        first = subprocess.CompletedProcess(args=[], returncode=0, stdout="line1\nline2\n", stderr="")
        stale = subprocess.CompletedProcess(args=[], returncode=0, stdout="line1\nline2\n", stderr="")
        with patch("kaggle_switch.logs_viewer.subprocess.run", side_effect=[first, stale, stale, stale, stale, stale]), \
             patch("kaggle_switch.logs_viewer.time.sleep"):
            batches = list(_poll_follow("owner/kernel"))
        assert len(batches) == 1
        assert [e.data for e in batches[0]] == ["line1", "line2"]

    def test_poll_follow_breaks_on_nonzero(self):
        bad = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="bad")
        with patch("kaggle_switch.logs_viewer.subprocess.run", return_value=bad):
            assert list(_poll_follow("owner/kernel")) == []

    def test_poll_follow_breaks_on_timeout(self):
        with patch("kaggle_switch.logs_viewer.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=60)):
            assert list(_poll_follow("owner/kernel")) == []


class TestRenderEdges:
    def test_is_progress_bar_detection(self):
        assert _is_progress_bar(" 45%|████ | 23/50 [00:45<01:30, 2.14it/s]") is True
        assert _is_progress_bar("normal line") is False

    def test_render_logs_empty_no_output(self):
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False)
        render_logs([], console=console)
        assert buf.getvalue() == ""

    def test_render_logs_filters_progress_by_default(self):
        entries = [
            LogEntry("stdout", 1.0, " 45%|████ | 23/50 [00:45<01:30, 2.14it/s]"),
            LogEntry("stdout", 2.0, "kept line"),
        ]
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False)
        render_logs(entries, console=console)
        out = buf.getvalue()
        assert "kept line" in out
        assert "45%|" not in out

    def test_render_logs_show_progress_true(self):
        entries = [LogEntry("stdout", 1.0, " 45%|████ | 23/50 [00:45<01:30, 2.14it/s]")]
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False)
        render_logs(entries, console=console, show_progress=True)
        assert "45%|" in buf.getvalue()

    def test_render_logs_truncates_overlong_line_and_negative_relative(self):
        long_line = "x" * 4100
        entries = [LogEntry("stdout", 5.0, long_line)]
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False)
        render_logs(entries, console=console, start_time=10.0)
        out = buf.getvalue()
        assert "…" in out or "..." in out
        assert "+    0s" in out or "+  0.0s" in out or "+    0s".strip() in out

    def test_render_result_displays_hint_panel(self):
        result = LogFetchResult(entries=[LogEntry("stderr", 0, "FloatingPointError: NaN in loss")])
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False)
        hint = render_result(result, console=console)
        out = buf.getvalue()
        assert hint is not None
        assert "Possible fix" in out

    def test_render_logs_help_prints_usage(self):
        with patch.object(lv.style_console, "print") as mock_print:
            render_logs_help()
        assert mock_print.call_count >= 5
        first_arg = mock_print.call_args_list[0][0][0]
        assert "Usage" in first_arg


class TestTryKaggleApi:
    def test_try_kaggle_api_failure_returns_none(self):
        original_import = __import__

        def fail_kaggle_import(name, *args, **kwargs):
            if name.startswith("kaggle.api.kaggle_api_extended"):
                raise ImportError("missing kaggle")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_kaggle_import):
            assert lv._try_kaggle_api() is None

