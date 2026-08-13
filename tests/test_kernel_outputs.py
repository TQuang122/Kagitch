"""Tests for kernel output download module."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import kaggle_switch.kernel_outputs as ko
from kaggle_switch.kernel_outputs import (
    KernelOutputError,
    OutputFile,
    download_files,
    fetch_sizes,
    list_output_files,
)


class FakeListApi:
    """kaggle client whose list_kernel_session_output returns pages."""

    def __init__(self, pages):
        self.pages = pages
        self.calls: list = []

    def list_kernel_session_output(self, request):
        self.calls.append(request)
        return self.pages.pop(0)


def _page(files, token=None, log=""):
    return SimpleNamespace(
        files=[SimpleNamespace(file_name=name, url=url) for name, url in files],
        log=log,
        next_page_token=token,
    )


def _patch_client(monkeypatch, api):
    monkeypatch.setattr("kaggle_switch.kernel_outputs._HAS_SDK", True)
    monkeypatch.setattr(
        "kaggle_switch.kernel_outputs._build_client",
        lambda: SimpleNamespace(kernels=SimpleNamespace(kernels_api_client=api)),
    )


def _fake_request(owner, slug, page_size, token, version_label):
    from types import SimpleNamespace

    return SimpleNamespace(
        user_name=owner, kernel_slug=slug, page_size=page_size,
        page_token=token, version_label=version_label,
    )


class TestListOutputFiles:
    @pytest.fixture(autouse=True)
    def _no_kagglesdk(self, monkeypatch):
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs._new_list_request", _fake_request
        )

    def test_lists_files_single_page(self, monkeypatch):
        api = FakeListApi([_page([("a.csv", "http://u/a")])])
        _patch_client(monkeypatch, api)

        files = list_output_files("owner", "slug")

        assert len(files) == 1
        assert files[0].path == "a.csv"
        assert files[0].url == "http://u/a"
        assert len(api.calls) == 1
        req = api.calls[0]
        assert req.user_name == "owner"
        assert req.kernel_slug == "slug"
        assert req.page_size == 100

    def test_paginates_until_token_exhausted(self, monkeypatch):
        api = FakeListApi([
            _page([("a.csv", "http://u/a")], token="t1"),
            _page([("sub/b.csv", "http://u/b")], token=None),
        ])
        _patch_client(monkeypatch, api)

        files = list_output_files("owner", "slug")

        assert [f.path for f in files] == ["a.csv", "sub/b.csv"]
        assert len(api.calls) == 2
        assert getattr(api.calls[1], "page_token", None) == "t1"

    def test_missing_sdk_raises(self, monkeypatch):
        monkeypatch.setattr("kaggle_switch.kernel_outputs._HAS_SDK", False)

        with pytest.raises(KernelOutputError, match="kagglesdk"):
            list_output_files("owner", "slug")

    def test_api_error_wrapped(self, monkeypatch):
        class BoomApi:
            def list_kernel_session_output(self, request):
                raise RuntimeError("boom")

        _patch_client(monkeypatch, BoomApi())

        with pytest.raises(KernelOutputError, match="boom"):
            list_output_files("owner", "slug")

    def test_log_included_as_synthetic_entry(self, monkeypatch):
        api = FakeListApi([_page([], token=None, log="kernel log text")])
        _patch_client(monkeypatch, api)

        files = list_output_files("owner", "slug")

        assert files[-1].path == "slug.log"
        assert files[-1].url is None
        assert files[-1].log_text == "kernel log text"

    def test_version_label_forwarded(self, monkeypatch):
        api = FakeListApi([_page([("a.csv", "http://u/a")])])
        _patch_client(monkeypatch, api)

        list_output_files("owner", "slug", version_label="3")

        assert api.calls[0].version_label == "3"


class FakeResponse:
    def __init__(self, status=200, chunks=(b"ab", b"cd"), headers=None):
        self.status_code = status
        self._chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        return iter(self._chunks)


class FakeSession:
    def __init__(self, status=200, headers=None, chunks=(b"ab", b"cd")):
        self.status = status
        self.headers = headers or {}
        self.chunks = chunks
        self.urls: list = []
        self.head_urls: list = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return FakeResponse(status=self.status, chunks=self.chunks)

    def head(self, url, **kwargs):
        self.head_urls.append(url)
        return FakeResponse(status=self.status, chunks=(), headers=self.headers)


class TestDownloadFiles:
    def test_downloads_nested_paths(self, tmp_path):
        session = FakeSession()
        files = [OutputFile(path="sub/a.csv", url="http://u/a")]

        downloaded, skipped = download_files(files, tmp_path, session=session)

        assert skipped == 0
        assert downloaded == [tmp_path / "sub" / "a.csv"]
        assert (tmp_path / "sub" / "a.csv").read_bytes() == b"abcd"
        assert session.urls == ["http://u/a"]

    def test_skips_existing_without_force(self, tmp_path):
        dest = tmp_path / "a.csv"
        dest.write_bytes(b"old")
        files = [OutputFile(path="a.csv", url="http://u/a")]

        downloaded, skipped = download_files(files, tmp_path, session=FakeSession())

        assert downloaded == []
        assert skipped == 1
        assert dest.read_bytes() == b"old"

    def test_force_overwrites_existing(self, tmp_path):
        dest = tmp_path / "a.csv"
        dest.write_bytes(b"old")
        files = [OutputFile(path="a.csv", url="http://u/a")]

        downloaded, skipped = download_files(
            files, tmp_path, force=True, session=FakeSession()
        )

        assert downloaded == [dest]
        assert skipped == 0
        assert dest.read_bytes() == b"abcd"

    def test_writes_log_entry_when_selected(self, tmp_path):
        files = [OutputFile(path="slug.log", url=None, log_text="log line")]

        downloaded, skipped = download_files(files, tmp_path, session=FakeSession())

        assert skipped == 0
        assert downloaded == [tmp_path / "slug.log"]
        assert (tmp_path / "slug.log").read_text() == "log line"

    def test_skips_url_none_without_log_text(self, tmp_path):
        files = [OutputFile(path="x.log", url=None, log_text="")]

        downloaded, skipped = download_files(files, tmp_path, session=FakeSession())

        assert downloaded == []
        assert skipped == 1

    def test_403_raises_friendly_error(self, tmp_path):
        files = [OutputFile(path="a.csv", url="http://u/a")]

        with pytest.raises(KernelOutputError, match="Cannot access kernel output"):
            download_files(files, tmp_path, session=FakeSession(status=403))

    def test_empty_list(self, tmp_path):
        assert download_files([], tmp_path, session=FakeSession()) == ([], 0)


class TestModuleGuards:
    def test_build_client_uses_kaggleclient(self, monkeypatch):
        api = FakeListApi([_page([("a.csv", "http://u/a")])])
        fake = SimpleNamespace(kernels=SimpleNamespace(kernels_api_client=api))
        monkeypatch.setattr("kaggle_switch.kernel_outputs._HAS_SDK", True)
        monkeypatch.setattr("kaggle_switch.kernel_outputs.KaggleClient", lambda: fake)
        monkeypatch.setattr(
            "kaggle_switch.kernel_outputs._new_list_request", _fake_request
        )

        files = list_output_files("owner", "slug")

        assert files[0].path == "a.csv"

    def test_requests_missing_raises(self, tmp_path):
        from unittest.mock import patch

        original_import = __import__

        def fail_requests(name, *args, **kwargs):
            if name == "requests":
                raise ImportError("missing")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_requests):
            with pytest.raises(KernelOutputError, match="requests"):
                download_files(
                    [OutputFile(path="a.csv", url="http://u/a")], tmp_path
                )


class TestFetchSizes:
    def test_sets_sizes_from_content_length(self):
        files = [
            OutputFile(path="a.csv", url="http://u/a"),
            OutputFile(path="b.csv", url="http://u/b"),
        ]
        session = FakeSession(headers={"Content-Length": "1024"})

        fetch_sizes(files, session=session)

        assert files[0].size == 1024
        assert files[1].size == 1024
        assert session.head_urls == ["http://u/a", "http://u/b"]

    def test_ignores_failures_and_missing_length(self):
        files = [
            OutputFile(path="a.csv", url="http://u/a"),
            OutputFile(path="b.csv", url="http://u/b"),
            OutputFile(path="c.log", url=None),
        ]
        session = FakeSession(status=403)

        fetch_sizes(files, session=session)

        assert files[0].size is None
        assert files[1].size is None
        assert files[2].size is None
        assert "http://u/b" in session.head_urls
        assert len(session.head_urls) == 2

    def test_empty_list_no_requests(self):
        fetch_sizes([], session=FakeSession())
        assert True


class TestDownloadProgress:
    def test_on_progress_reports_chunks_and_final(self, tmp_path):
        files = [OutputFile(path="a.csv", url="http://u/a", size=4)]
        calls = []
        download_files(
            files, tmp_path, session=FakeSession(),
            on_progress=lambda dest, done, total: calls.append((done, total)),
        )
        assert calls == [(2, 4), (4, 4), (4, 4)]

    def test_on_progress_unknown_size(self, tmp_path):
        files = [OutputFile(path="a.csv", url="http://u/a")]
        calls = []
        download_files(
            files, tmp_path, session=FakeSession(),
            on_progress=lambda dest, done, total: calls.append((done, total)),
        )
        assert calls == [(2, None), (4, None), (4, None)]

    def test_on_progress_log_entry(self, tmp_path):
        files = [OutputFile(path="slug.log", url=None, log_text="log line")]
        calls = []
        download_files(
            files, tmp_path, session=FakeSession(),
            on_progress=lambda dest, done, total: calls.append((done, total)),
        )
        assert calls == [(8, 8)]


class TestModuleGuards2:
    def test_fetch_sizes_requests_missing_raises(self):
        from unittest.mock import patch

        original_import = __import__

        def fail_requests(name, *args, **kwargs):
            if name == "requests":
                raise ImportError("missing")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_requests):
            with pytest.raises(KernelOutputError, match="requests"):
                fetch_sizes([OutputFile(path="a.csv", url="http://u/a")])

    def test_download_skips_empty_chunk(self, tmp_path):
        files = [OutputFile(path="a.csv", url="http://u/a", size=4)]
        calls = []
        download_files(
            files, tmp_path, session=FakeSession(chunks=(b"", b"ab")),
            on_progress=lambda dest, done, total: calls.append((done, total)),
        )
        assert (tmp_path / "a.csv").read_bytes() == b"ab"
        assert calls == [(2, 4), (2, 4)]


class RaisingHeadSession(FakeSession):
    def head(self, url, **kwargs):
        raise OSError("no head support")


class TestFetchSizesErrors:
    def test_ignores_head_exceptions(self):
        files = [OutputFile(path="a.csv", url="http://u/a")]

        fetch_sizes(files, session=RaisingHeadSession())

        assert files[0].size is None


class TestNewListRequest:
    def test_builds_request_with_fields(self):
        pytest.importorskip("kagglesdk")
        from kaggle_switch.kernel_outputs import _new_list_request

        req = _new_list_request("owner", "slug", 100, "tok", "3")
        assert req.user_name == "owner"
        assert req.kernel_slug == "slug"
        assert req.page_size == 100
        assert req.page_token == "tok"
        assert req.version_label == "3"

    def test_omits_optional_fields(self):
        pytest.importorskip("kagglesdk")
        from kaggle_switch.kernel_outputs import _new_list_request

        req = _new_list_request("owner", "slug", 100, None, None)
        assert not req.page_token
        assert not req.version_label
