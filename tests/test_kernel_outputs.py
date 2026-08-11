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


class TestListOutputFiles:
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
    def __init__(self, status=200, chunks=(b"ab", b"cd")):
        self.status_code = status
        self._chunks = chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        return iter(self._chunks)


class FakeSession:
    def __init__(self, status=200):
        self.status = status
        self.urls: list = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return FakeResponse(status=self.status)


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
