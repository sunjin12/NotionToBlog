"""Image pipeline — hashed filenames for Hugo page bundles.

Notion serves images from signed S3 URLs that expire ~1h after retrieval
(domain-notes §6), so we must download each image during the publish run.
Filenames are derived from ``sha1(page_id:block_id)`` truncated to 10 chars —
stable across reruns of the same Notion page even if the URL rotates.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

KNOWN_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")
FALLBACK_EXT = ".bin"


@dataclass(frozen=True)
class ImageRef:
    block_id: str
    url: str
    caption: str
    filename: str  # e.g. "img-a1b2c3d4e5.png" (no leading ./)

    @property
    def markdown_href(self) -> str:
        return f"./{self.filename}"


@dataclass
class ImageCollector:
    """Accumulates image references during a render pass.

    The renderer calls :meth:`register` for each ``image`` block it encounters;
    the return value is a relative markdown href ready to embed in the output.
    :meth:`download_all` is invoked later (Phase 3) to materialize the files
    inside the page bundle.
    """

    page_id: str
    refs: list[ImageRef] = field(default_factory=list)

    def register(self, *, block_id: str, url: str, caption: str = "") -> ImageRef:
        filename = _hashed_filename(self.page_id, block_id, url)
        ref = ImageRef(block_id=block_id, url=url, caption=caption, filename=filename)
        self.refs.append(ref)
        return ref


def download_all(
    refs: list[ImageRef],
    bundle_dir: Path,
    *,
    http_get: Callable[[str], bytes],
    max_bytes_warn: int = 20 * 1024 * 1024,
    warn: Callable[[str], None] = lambda _msg: None,
) -> list[Path]:
    """Fetch each ref's URL into ``bundle_dir/<filename>``. Skips existing files.

    ``http_get`` is injected for testability — real callers pass an ``httpx`` GET
    helper, tests pass a dict-backed stub. Returns the list of on-disk paths in
    the same order as ``refs``.
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ref in refs:
        target = bundle_dir / ref.filename
        if target.exists():
            paths.append(target)
            continue
        data = http_get(ref.url)
        if len(data) > max_bytes_warn:
            warn(f"image {ref.filename} exceeds soft limit: {len(data)} > {max_bytes_warn} bytes")
        target.write_bytes(data)
        paths.append(target)
    return paths


# --- internals ----------------------------------------------------------------


def _hashed_filename(page_id: str, block_id: str, url: str) -> str:
    digest = hashlib.sha1(f"{page_id}:{block_id}".encode("utf-8")).hexdigest()[:10]
    ext = _guess_ext(url)
    return f"img-{digest}{ext}"


def _guess_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in KNOWN_EXTS:
        if path.endswith(ext):
            return ext
    return FALLBACK_EXT
