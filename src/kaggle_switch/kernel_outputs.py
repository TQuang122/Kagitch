"""Kernel output listing and download via kagglesdk signed URLs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_HAS_SDK = False
try:
    from kagglesdk import KaggleClient

    _HAS_SDK = True
except Exception:
    pass  # kagglesdk not installed — listing will raise KernelOutputError


@dataclass
class OutputFile:
    path: str
    url: str | None = None
    log_text: str = ""
    size: int | None = None


class KernelOutputError(Exception):
    """User-facing error while listing or downloading kernel outputs."""


def _build_client() -> KaggleClient:
    return KaggleClient()


def _new_list_request(owner: str, slug: str, page_size: int, token: str | None, version_label: str | None):
    from kagglesdk.kernels.types.kernels_api_service import ApiListKernelSessionOutputRequest

    request = ApiListKernelSessionOutputRequest()
    request.user_name = owner
    request.kernel_slug = slug
    request.page_size = page_size
    if token:
        request.page_token = token
    if version_label:
        request.version_label = version_label
    return request


def list_output_files(
    owner: str,
    slug: str,
    *,
    page_size: int = 100,
    version_label: str | None = None,
) -> list[OutputFile]:
    """List a kernel's output files, paginated, plus its log when present."""
    if not _HAS_SDK:
        raise KernelOutputError(
            "kagglesdk is required to list kernel outputs. Install with: pip install kaggle"
        )
    files: list[OutputFile] = []
    log = ""
    token: str | None = None
    try:
        api = _build_client().kernels.kernels_api_client
        while True:
            response = api.list_kernel_session_output(
                _new_list_request(owner, slug, page_size, token, version_label)
            )
            for f in response.files or []:
                files.append(OutputFile(path=f.file_name, url=f.url))
            if response.log:
                log = response.log
            token = response.next_page_token or None
            if not token:
                break
    except Exception as e:
        raise KernelOutputError(str(e)[:200] or e.__class__.__name__) from e
    if log:
        files.append(OutputFile(path=f"{slug}.log", url=None, log_text=log))
    return files


def fetch_sizes(files: list[OutputFile], *, session=None, max_workers: int = 8) -> None:
    """Populate *size* on each file via parallel HEAD requests.

    Failures leave the size as None so the caller can show a placeholder.
    """
    targets = [f for f in files if f.url]
    if not targets:
        return
    try:
        import requests
    except ImportError as e:
        raise KernelOutputError(
            "requests is required to download files. Install with: pip install kaggle"
        ) from e

    sess = session if session is not None else requests.Session()

    def _head(f: OutputFile) -> None:
        try:
            resp = sess.head(f.url, timeout=10)
            if resp.status_code == 200 and resp.headers.get("Content-Length"):
                f.size = int(resp.headers["Content-Length"])
        except (OSError, ValueError):
            pass

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_head, targets))


def download_files(
    files: list[OutputFile],
    target_dir: Path,
    *,
    force: bool = False,
    session=None,
    on_progress: Callable[[Path, int, int | None], None] | None = None,
) -> tuple[list[Path], int]:
    """Stream each file's signed URL into *target_dir*.

    Returns (downloaded paths, skipped count).  Entries without a URL
    (e.g. the kernel log) and existing files without *force* are skipped.
    *on_progress* is called per chunk and once more with the final
    byte count.
    """
    try:
        import requests
    except ImportError as e:
        raise KernelOutputError(
            "requests is required to download files. Install with: pip install kaggle"
        ) from e

    target = Path(target_dir)
    sess = session if session is not None else requests.Session()
    downloaded: list[Path] = []
    skipped = 0
    for f in files:
        dest = target / f.path
        if dest.exists() and not force:
            skipped += 1
            continue
        if not f.url:
            if f.log_text:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(f.log_text)
                if on_progress:
                    on_progress(dest, len(f.log_text.encode()), len(f.log_text.encode()))
                downloaded.append(dest)
            else:
                skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        resp = sess.get(f.url, stream=True, timeout=15)
        if resp.status_code in (401, 403):
            raise KernelOutputError(
                f"Cannot access kernel output (HTTP {resp.status_code}). "
                "The download URL may have expired - retry the command."
            )
        resp.raise_for_status()
        done = 0
        with open(dest, "wb") as out:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                out.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(dest, done, f.size)
        if on_progress:
            on_progress(dest, done, f.size)
        downloaded.append(dest)
    return downloaded, skipped
