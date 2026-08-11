"""Kernel output listing and download via kagglesdk signed URLs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def download_files(
    files: list[OutputFile],
    target_dir: Path,
    *,
    force: bool = False,
    session=None,
) -> tuple[list[Path], int]:
    """Stream each file's signed URL into *target_dir*.

    Returns (downloaded paths, skipped count).  Entries without a URL
    (e.g. the kernel log) and existing files without *force* are skipped.
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
        with open(dest, "wb") as out:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    out.write(chunk)
        downloaded.append(dest)
    return downloaded, skipped
